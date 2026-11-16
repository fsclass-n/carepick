import hashlib
import json
import os
import re
import sys

import boto3
import requests
from sqlalchemy import select

from backend.db import Base, SessionLocal, engine
from backend.models import Food


def grams(value):
    text = str(value or "").strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:g|그램)?", text)
    return float(match.group(1)) if match and float(match.group(1)) > 0 else None


def nutrient(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize(row):
    """The MFDS I2790 nutrients are per serving; store values per 100g."""
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


def sync():
    key = os.getenv("MFDS_API_KEY")
    if not key:
        raise RuntimeError("MFDS_API_KEY is required to sync food data")
    max_pages = int(os.getenv("SYNC_MAX_PAGES", "10"))
    if max_pages < 1:
        raise ValueError("SYNC_MAX_PAGES must be positive")
    Base.metadata.create_all(engine)
    saved = 0
    bucket = os.getenv("S3_BUCKET")
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION") or "ap-northeast-2") if bucket else None
    for page in range(max_pages):
        start, end = page * 1000 + 1, (page + 1) * 1000
        url = f"https://openapi.foodsafetykorea.go.kr/api/{key}/I2790/json/{start}/{end}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        result = response.json().get("I2790", {})
        status = result.get("RESULT", {}).get("CODE")
        if status == "INFO-200":
            break
        if status != "INFO-000":
            raise RuntimeError(f"MFDS API error: {status or 'missing result'}")
        rows = result.get("row", [])
        if s3:
            s3.put_object(
                Bucket=bucket,
                Key=f"mfds/I2790/page-{page + 1:04d}.json",
                Body=json.dumps(result, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        with SessionLocal() as db:
            for row in rows:
                data = normalize(row)
                if data is None:
                    continue
                food = db.scalar(select(Food).where(Food.source_id == data["source_id"]))
                if food:
                    for field, value in data.items():
                        setattr(food, field, value)
                else:
                    db.add(Food(**data))
                saved += 1
            db.commit()
        print(f"Page {page + 1}: {len(rows)} rows, {saved} valid rows saved")
        if len(rows) < 1000:
            break
    return saved


if __name__ == "__main__":
    try:
        print(f"Synced {sync()} food rows")
    except (requests.RequestException, ValueError, RuntimeError):
        # Request exceptions may contain the API key embedded in the URL.
        print("Food sync failed; check API credentials, network and data format.", file=sys.stderr)
        sys.exit(1)
