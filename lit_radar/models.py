from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Paper:
    source: str
    id: str
    title: str
    url: str
    published_at: str | None
    authors: list[str]
    summary: str | None
    tags: list[str]


@dataclass(frozen=True)
class ScoredPaper:
    source: str
    id: str
    title: str
    url: str
    published_at: str | None
    authors: list[str]
    summary: str | None
    tags: list[str]
    score: float
    matched_terms: list[str]

