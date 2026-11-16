import hashlib
import math
import os
import re
import sys
from urllib.parse import unquote

import requests
from sqlalchemy import select

from backend.db import Base, SessionLocal, engine
from backend.models import Food

API_URL = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03"
PAGE_SIZE = 500


def grams(value):
    text = str(value or "").strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:g|그램)?", text)
    return float(match.group(1)) if match and float(match.group(1)) > 0 else None


def nutrient(value):
    try:
        number = float(str(value).replace(",", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalize(row):
    """Convert MFDS serving-based nutrients to amounts per 100g."""
    size = grams(row.get("SERVING_SIZE"))
    name = (row.get("DESC_KOR") or row.get("FOOD_NM_KR") or "").strip()
    keys = ("NUTR_CONT1", "NUTR_CONT3", "NUTR_CONT2", "NUTR_CONT4") if "NUTR_CONT1" in row else (
        "AMT_NUM1", "AMT_NUM3", "AMT_NUM6", "AMT_NUM4"
    )
    raw = [nutrient(row.get(key)) for key in keys]
    if not name or not size or any(value is None or value < 0 for value in raw):
        return None
    source_id = str(row.get("FOOD_CD") or "").strip() or hashlib.sha256(
        f'{name}:{row.get("MAKER_NAME", "")}'.encode()
    ).hexdigest()
    return {"source_id": source_id[:100], "name": name[:255], **{
        key: round(value * 100 / size, 2)
        for key, value in zip(("calories", "protein", "carbs", "fat"), raw)
    }}


def fetch_page(key, page):
    # The portal provides both raw and URL-encoded keys; requests encodes the query once.
    response = requests.get(
        API_URL,
        params={"serviceKey": unquote(key), "pageNo": page, "numOfRows": PAGE_SIZE, "type": "json"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("header"), dict):
        raise ValueError("Unexpected public data response")
    code = str(payload["header"].get("resultCode", ""))
    if code != "00":
        raise RuntimeError(f"MFDS public data API error code: {code}")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ValueError("Missing public data response body")
    rows = body.get("items", [])
    if not isinstance(rows, list) or not isinstance(body.get("totalCount"), (str, int)):
        raise ValueError("Unexpected public data response items")
    return rows, int(body["totalCount"])


def sync():
    key = os.getenv("MFDS_API_KEY")
    if not key:
        raise RuntimeError("MFDS_API_KEY is required to sync food data")
    max_pages = int(os.getenv("SYNC_MAX_PAGES", "10"))
    if max_pages < 1:
        raise ValueError("SYNC_MAX_PAGES must be positive")
    Base.metadata.create_all(engine)
    saved = 0
    total = 0
    for page in range(1, max_pages + 1):
        rows, total = fetch_page(key, page)
        if not rows:
            if total:
                raise RuntimeError("Public data response contains no items before the last page")
            break
        foods = {}
        for row in rows:
            data = normalize(row)
            if data is not None:
                foods[data["source_id"]] = data
        with SessionLocal() as db:
            existing = {
                food.source_id: food
                for food in db.scalars(select(Food).where(Food.source_id.in_(foods))).all()
            } if foods else {}
            for source_id, data in foods.items():
                if source_id in existing:
                    for field, value in data.items():
                        setattr(existing[source_id], field, value)
                else:
                    db.add(Food(**data))
            db.commit()
        saved += len(foods)
        print(f"Page {page}: {len(rows)} rows, {saved} valid rows saved")
        if page * PAGE_SIZE >= total:
            break
        if len(rows) < PAGE_SIZE:
            raise RuntimeError("Unexpected short page from public data API")
    if total and not saved:
        raise RuntimeError("No usable gram-based nutrition rows were found")
    return saved


if __name__ == "__main__":
    try:
        print(f"Synced {sync()} food rows")
    except (requests.RequestException, ValueError, RuntimeError):
        # Request exceptions may contain the API key embedded in the URL.
        print("Food sync failed; check API credentials, network and data format.", file=sys.stderr)
        sys.exit(1)
