from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import feedparser

from .models import Paper
from .utils import get_with_retry, norm_space, utc_now


def fetch_arxiv(window_hours: int, query: str, max_results: int, *, timeout_seconds: float, retries: int) -> list[Paper]:
    base = "http://export.arxiv.org/api/query"
    since = utc_now() - timedelta(hours=window_hours)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    r = get_with_retry(base, params=params, timeout_seconds=timeout_seconds, retries=retries)
    feed = feedparser.parse(r.text)
    out: list[Paper] = []
    for e in feed.entries:
        published = None
        if getattr(e, "published", None):
            published = e.published
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if dt < since:
                    continue
            except Exception:
                pass
        paper_id = e.get("id", "")
        title = norm_space(e.get("title", ""))
        summary = norm_space(e.get("summary", "")) or None
        authors = [a.get("name", "").strip() for a in e.get("authors", []) if a.get("name")]
        tags = [t.get("term", "") for t in e.get("tags", []) if t.get("term")]
        if not paper_id or not title:
            continue
        out.append(
            Paper(
                source="arxiv",
                id=paper_id,
                title=title,
                url=paper_id,
                published_at=published,
                authors=authors,
                summary=summary,
                tags=tags,
            )
        )
    return out


def fetch_hf_papers(window_hours: int, max_items: int, *, timeout_seconds: float, retries: int) -> list[Paper]:
    since = utc_now() - timedelta(hours=window_hours)
    days = {(since + timedelta(hours=i)).date() for i in range(0, window_hours + 1, 6)}
    out: list[Paper] = []
    seen_ids: set[str] = set()
    for d in sorted(days, reverse=True):
        url = "https://huggingface.co/papers"
        r = get_with_retry(url, params={"date": d.isoformat()}, timeout_seconds=timeout_seconds, retries=retries)
        html = r.text
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        stack = [data]
        items = None
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if "papers" in cur and isinstance(cur["papers"], list):
                    items = cur["papers"]
                    break
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        if not isinstance(items, list):
            continue
        for it in items:
            if len(out) >= max_items:
                break
            if not isinstance(it, dict):
                continue
            pid = str(it.get("id") or it.get("paperId") or it.get("arxivId") or "").strip()
            title = norm_space(str(it.get("title") or ""))
            paper_url = str(it.get("url") or it.get("paperUrl") or "").strip()
            if not paper_url and pid:
                paper_url = f"https://huggingface.co/papers/{pid}"
            summary = norm_space(str(it.get("summary") or it.get("abstract") or "")) or None
            authors = [str(a).strip() for a in it.get("authors", []) if str(a).strip()] if isinstance(it.get("authors"), list) else []
            tags = [str(t).strip() for t in it.get("tags", []) if str(t).strip()] if isinstance(it.get("tags"), list) else []
            published_at = it.get("publishedAt") or it.get("published_at") or it.get("date")
            pid_key = pid or paper_url or title
            if not pid_key or pid_key in seen_ids or not title or not paper_url:
                continue
            seen_ids.add(pid_key)
            out.append(
                Paper(
                    source="hf",
                    id=pid_key,
                    title=title,
                    url=paper_url,
                    published_at=str(published_at) if published_at else None,
                    authors=authors,
                    summary=summary,
                    tags=tags,
                )
            )
        if len(out) >= max_items:
            break
    return out

