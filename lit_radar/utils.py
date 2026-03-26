from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

import requests
from requests.exceptions import RequestException


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_keywords(s: str | None) -> list[str]:
    if not s:
        return []
    return [k.strip().lower() for k in s.split(",") if k.strip()]


def keyword_match(title: str, summary: str | None, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = (title + "\n" + (summary or "")).lower()
    return any(k in hay for k in keywords)


def exclude_match(title: str, summary: str | None, exclude: list[str]) -> bool:
    if not exclude:
        return False
    hay = (title + "\n" + (summary or "")).lower()
    return any(k in hay for k in exclude)


def ensure_out_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_with_retry(url: str, *, params: dict | None, timeout_seconds: float, retries: int) -> requests.Response:
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            r = requests.get(url, params=params, timeout=timeout_seconds)
            r.raise_for_status()
            return r
        except RequestException as e:
            last_err = e
            if attempt < max(1, retries) - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_err or RuntimeError("request failed")

