import json
import os
from datetime import datetime, timedelta
from typing import Optional

CACHE_DIR = "cache"
CACHE_DURATION_HOURS = 24


def _get_cache_filepath(key: str) -> str:
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    return os.path.join(CACHE_DIR, f"{key}.json")


def is_cache_valid(key: str) -> bool:
    filepath = _get_cache_filepath(key)
    if not os.path.exists(filepath):
        return False

    try:
        with open(filepath, "r") as f:
            data = json.load(f)
            timestamp = datetime.fromisoformat(data["timestamp"])
            if datetime.utcnow() - timestamp > timedelta(hours=CACHE_DURATION_HOURS):
                return False
            return True
    except (json.JSONDecodeError, KeyError):
        return False


def load_from_cache(key: str) -> Optional[dict]:
    if not is_cache_valid(key):
        return None

    filepath = _get_cache_filepath(key)
    try:
        with open(filepath, "r") as f:
            return json.load(f)["data"]
    except (json.JSONDecodeError, KeyError, FileNotFoundError):
        return None


def save_to_cache(key: str, data: dict):
    filepath = _get_cache_filepath(key)
    cache_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "data": data,
    }
    with open(filepath, "w") as f:
        json.dump(cache_data, f, indent=4)
