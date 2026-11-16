import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base, get_db
from backend import main
from backend.main import app
from backend.models import Food, OAuthTicket, User, utc_now


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    def test_db():
        with session() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client, session
    app.dependency_overrides.clear()
    engine.dispose()


def register(client, email):
    response = client.post("/api/auth/register", json={"email": email, "name": "테스터", "password": "ValidPass1!"})
    assert response.status_code == 201
    return {"Authorization": f'Bearer {response.json()["access_token"]}'}


def test_auth_policy_and_private_meals(client):
    web, _ = client
    weak = web.post("/api/auth/register", json={"email": "weak@example.com", "name": "테스터", "password": "weakpass"})
    assert weak.status_code == 422
    first = register(web, "one@example.com")
    second = register(web, "two@example.com")
    assert web.post("/api/auth/login", json={"email": "one@example.com", "password": "wrong"}).status_code == 401
    assert web.get("/api/meals").status_code == 401
    meal = web.post("/api/meals", headers=first, json={
        "food_name": "현미밥", "meal_type": "점심", "eaten_at": "2026-11-16",
        "serving_g": 150, "calories": 220, "protein": 4, "carbs": 45, "fat": 1,
    })
    assert meal.status_code == 201
    assert len(web.get("/api/meals", headers=first).json()) == 1
    assert web.get("/api/meals", headers=second).json() == []
    assert web.delete(f'/api/meals/{meal.json()["id"]}', headers=second).status_code == 404
    assert web.delete(f'/api/meals/{meal.json()["id"]}', headers=first).status_code == 204
    assert web.get("/api/meals", headers=first).json() == []


def test_netlify_origin_can_call_api(client):
    web, _ = client
    response = web.options("/api/meals", headers={
        "Origin": "https://carepick.netlify.app",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://carepick.netlify.app"


def test_admin_role_change_is_enforced_server_side(client):
    web, session = client
    first = register(web, "admin@example.com")
    second = register(web, "member@example.com")
    with session() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        admin.role = "admin"
        admin_id = admin.id
        member_id = db.query(User).filter_by(email="member@example.com").one().id
        db.commit()
    assert web.get("/api/admin/users", headers=second).status_code == 403
    assert web.patch(f"/api/admin/users/{member_id}/role", headers=second, json={"role": "admin"}).status_code == 403
    assert web.patch(f"/api/admin/users/{admin_id}/role", headers=first, json={"role": "user"}).status_code == 400
    assert web.patch(f"/api/admin/users/{member_id}/role", headers=first, json={"role": "admin"}).json()["role"] == "admin"
    assert web.get("/api/admin/users", headers=second).status_code == 200
    assert web.patch(f"/api/admin/users/{member_id}/role", headers=first, json={"role": "user"}).json()["role"] == "user"
    assert web.get("/api/admin/users", headers=second).status_code == 403


def test_oauth_ticket_is_one_time_and_expires(client):
    web, session = client
    register(web, "member@example.com")
    with session() as db:
        user = db.query(User).filter_by(email="member@example.com").one()
        db.add(OAuthTicket(code_hash=hashlib.sha256(b"fresh").hexdigest(), user_id=user.id, expires_at=utc_now() + timedelta(minutes=1)))
        db.add(OAuthTicket(code_hash=hashlib.sha256(b"stale").hexdigest(), user_id=user.id, expires_at=utc_now() - timedelta(minutes=1)))
        db.commit()
    assert web.post("/api/auth/oauth/exchange", json={"code": "stale"}).status_code == 401
    assert web.post("/api/auth/oauth/exchange", json={"code": "fresh"}).status_code == 200
    assert web.post("/api/auth/oauth/exchange", json={"code": "fresh"}).status_code == 401


def test_personalized_targets_are_private_and_estimated(client):
    web, _ = client
    first = register(web, "one@example.com")
    second = register(web, "two@example.com")
    assert web.get("/api/nutrition/targets", headers=first).json()["personalized"] is False
    profile = {"age": 30, "biological_sex": "female", "height_cm": 165, "weight_kg": 60, "activity_level": "light"}
    response = web.patch("/api/nutrition/profile", headers=first, json=profile)
    assert response.status_code == 200
    # Mifflin-St Jeor: 600 + 1031.25 - 150 - 161 = 1320.25; light activity x 1.375.
    assert response.json()["targets"]["calories"] == 1820
    assert web.get("/api/nutrition/targets", headers=first).json()["personalized"] is True
    assert web.get("/api/nutrition/targets", headers=second).json()["personalized"] is False
    assert web.patch("/api/nutrition/profile", headers=first, json={**profile, "age": 12}).status_code == 422


def test_food_sync_normalizes_only_valid_gram_servings():
    from rpa.sync_foods import normalize

    row = {"FOOD_CD": "A1", "DESC_KOR": "현미밥", "SERVING_SIZE": "200g",
           "NUTR_CONT1": "300", "NUTR_CONT2": "60", "NUTR_CONT3": "8", "NUTR_CONT4": "2"}
    assert normalize(row) == {"source_id": "A1", "name": "현미밥", "calories": 150, "protein": 4, "carbs": 30, "fat": 1}
    assert normalize({**row, "SERVING_SIZE": "200ml"}) is None
    modern = {"FOOD_CD": "B1", "FOOD_NM_KR": "기장밥", "SERVING_SIZE": "100g",
              "AMT_NUM1": "120", "AMT_NUM3": "2", "AMT_NUM6": "26", "AMT_NUM4": "0.5"}
    assert normalize(modern) == {"source_id": "B1", "name": "기장밥", "calories": 120, "protein": 2, "carbs": 26, "fat": 0.5}
    assert normalize({**modern, "AMT_NUM1": "nan"}) is None


def test_portal_api_page_uses_issued_key_and_checks_response(monkeypatch):
    from rpa import sync_foods

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                    "body": {"totalCount": 2, "items": [{"FOOD_CD": "A1"}]}}

    def fake_get(url, params, timeout):
        assert url == sync_foods.API_URL
        assert params == {"serviceKey": "a+b/=", "pageNo": 1, "numOfRows": 500, "type": "json"}
        assert timeout == 30
        return Response()

    monkeypatch.setattr(sync_foods.requests, "get", fake_get)
    assert sync_foods.fetch_page("a%2Bb%2F%3D", 1) == ([{"FOOD_CD": "A1"}], 2)

    class ErrorResponse(Response):
        def json(self):
            return {"header": {"resultCode": "20", "resultMsg": "SERVICE_KEY_IS_NULL"}}

    monkeypatch.setattr(sync_foods.requests, "get", lambda *args, **kwargs: ErrorResponse())
    with pytest.raises(RuntimeError, match="error code: 20"):
        sync_foods.fetch_page("key", 1)


def test_portal_sync_upserts_across_pages_without_duplicates(monkeypatch):
    from rpa import sync_foods

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(sync_foods, "engine", engine)
    monkeypatch.setattr(sync_foods, "SessionLocal", session)
    monkeypatch.setattr(sync_foods, "PAGE_SIZE", 2)
    monkeypatch.setenv("MFDS_API_KEY", "test-key")
    monkeypatch.setenv("SYNC_MAX_PAGES", "2")

    def row(code, energy):
        return {"FOOD_CD": code, "FOOD_NM_KR": "현미밥", "SERVING_SIZE": "100g",
                "AMT_NUM1": energy, "AMT_NUM3": "4", "AMT_NUM6": "25", "AMT_NUM4": "1"}

    pages = {1: ([row("A1", "100"), row("B1", "200")], 3), 2: ([row("A1", "120")], 3)}
    monkeypatch.setattr(sync_foods, "fetch_page", lambda key, page: pages[page])
    assert sync_foods.sync() == 3
    with session() as db:
        assert db.query(Food).count() == 2
        assert db.query(Food).filter_by(source_id="A1").one().calories == 120
    engine.dispose()


def test_invalid_admin_password_skips_bootstrap_without_crashing(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", session)
    monkeypatch.setenv("ADMIN_EMAIL", "Admin@Example.com")
    for password, admins in (("weakpass", 0), ("ValidPass1!", 1)):
        monkeypatch.setenv("ADMIN_PASSWORD", password)
        with TestClient(app) as web:
            assert web.get("/api/health").status_code == 200
        with session() as db:
            assert db.query(User).filter_by(email="admin@example.com", role="admin").count() == admins
    engine.dispose()
