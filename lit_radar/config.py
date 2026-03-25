from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Settings:
    window_hours: int = 24
    sources: str = "arxiv,hf"
    query: str = "cat:cs.RO OR cat:cs.AI OR cat:cs.LG"
    keywords: str = ""
    max_results: int = 50
    profile: str = "general"
    min_score: float = 0.0
    include_seen: bool = False
    timeout_seconds: float = 60.0
    retries: int = 3
    out: str = "out"
    db: str = ""


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"config must be a JSON object: {path}")
    return data


def _coalesce(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def resolve_settings(cli: Any, cfg: dict[str, Any]) -> Settings:
    """
    Merge order (later wins):
    - defaults (Settings)
    - config file (cfg)
    - CLI args (cli)
    """
    d = Settings()
    return Settings(
        window_hours=int(_coalesce(getattr(cli, "window_hours", None), cfg.get("window_hours"), d.window_hours)),
        sources=str(_coalesce(getattr(cli, "sources", None), cfg.get("sources"), d.sources)),
        query=str(_coalesce(getattr(cli, "query", None), cfg.get("query"), d.query)),
        keywords=str(_coalesce(getattr(cli, "keywords", None), cfg.get("keywords"), d.keywords)),
        max_results=int(_coalesce(getattr(cli, "max_results", None), cfg.get("max_results"), d.max_results)),
        profile=str(_coalesce(getattr(cli, "profile", None), cfg.get("profile"), d.profile)).strip(),
        min_score=float(_coalesce(getattr(cli, "min_score", None), cfg.get("min_score"), d.min_score)),
        include_seen=bool(_coalesce(getattr(cli, "include_seen", None), cfg.get("include_seen"), d.include_seen)),
        timeout_seconds=float(_coalesce(getattr(cli, "timeout_seconds", None), cfg.get("timeout_seconds"), d.timeout_seconds)),
        retries=int(_coalesce(getattr(cli, "retries", None), cfg.get("retries"), d.retries)),
        out=str(_coalesce(getattr(cli, "out", None), cfg.get("out"), d.out)),
        db=str(_coalesce(getattr(cli, "db", None), cfg.get("db"), d.db)),
    )

