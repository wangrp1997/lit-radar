from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

import feedparser
import requests


Source = Literal["arxiv", "hf"]


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _parse_keywords(s: str | None) -> list[str]:
    if not s:
        return []
    return [k.strip().lower() for k in s.split(",") if k.strip()]


def _keyword_match(title: str, summary: str | None, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = (title + "\n" + (summary or "")).lower()
    return any(k in hay for k in keywords)


def _ensure_out_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
          source TEXT NOT NULL,
          paper_id TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          published_at TEXT,
          authors_json TEXT NOT NULL,
          summary TEXT,
          tags_json TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          PRIMARY KEY (source, paper_id)
        )
        """
    )
    return conn


def _db_seen(conn: sqlite3.Connection, p: Paper) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM papers WHERE source=? AND paper_id=? LIMIT 1",
        (p.source, p.id),
    )
    return cur.fetchone() is not None


def _db_insert(conn: sqlite3.Connection, p: Paper) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO papers (
          source, paper_id, title, url, published_at, authors_json, summary, tags_json, first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            p.source,
            p.id,
            p.title,
            p.url,
            p.published_at,
            json.dumps(p.authors, ensure_ascii=False),
            p.summary,
            json.dumps(p.tags, ensure_ascii=False),
            _utc_now().isoformat(),
        ),
    )


def fetch_arxiv(window_hours: int, query: str, max_results: int = 50) -> list[Paper]:
    # arXiv API: http://export.arxiv.org/api/query
    # We keep it simple + robust: Atom feed parse.
    base = "http://export.arxiv.org/api/query"
    since = _utc_now() - timedelta(hours=window_hours)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    r = requests.get(base, params=params, timeout=30)
    r.raise_for_status()
    feed = feedparser.parse(r.text)
    out: list[Paper] = []
    for e in feed.entries:
        published = None
        if getattr(e, "published", None):
            published = e.published
            try:
                # e.g. 2026-03-25T00:00:00Z
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if dt < since:
                    continue
            except Exception:
                pass
        paper_id = e.get("id", "")
        title = _norm_space(e.get("title", ""))
        summary = _norm_space(e.get("summary", "")) or None
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


def fetch_hf_papers(window_hours: int, max_items: int = 50) -> list[Paper]:
    # Hugging Face Papers RSS can require auth in some environments.
    # The /api/papers/search endpoint can be picky about params (we observed 400 for date-only).
    # Use the public web page and extract __NEXT_DATA__ JSON (no auth required):
    # https://huggingface.co/papers?date=YYYY-MM-DD
    since = _utc_now() - timedelta(hours=window_hours)
    # We'll query by date for each day in the window (UTC) and then filter by timestamp when available.
    # If the API response lacks timestamps, we treat date-bucketed results as "in window".
    days = {(since + timedelta(hours=i)).date() for i in range(0, window_hours + 1, 6)}
    out: list[Paper] = []
    seen_ids: set[str] = set()
    for d in sorted(days, reverse=True):
        url = "https://huggingface.co/papers"
        r = requests.get(url, params={"date": d.isoformat()}, timeout=30)
        r.raise_for_status()
        html = r.text
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue

        # Find the first "papers" list in the JSON tree.
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
            title = _norm_space(str(it.get("title") or ""))
            url = str(it.get("url") or it.get("paperUrl") or "").strip()
            if not url and pid:
                url = f"https://huggingface.co/papers/{pid}"
            summary = _norm_space(str(it.get("summary") or it.get("abstract") or "")) or None
            authors = []
            if isinstance(it.get("authors"), list):
                authors = [str(a).strip() for a in it["authors"] if str(a).strip()]
            tags = []
            if isinstance(it.get("tags"), list):
                tags = [str(t).strip() for t in it["tags"] if str(t).strip()]
            published_at = it.get("publishedAt") or it.get("published_at") or it.get("date")
            pid_key = pid or url or title
            if not pid_key or pid_key in seen_ids or not title or not url:
                continue
            seen_ids.add(pid_key)
            out.append(
                Paper(
                    source="hf",
                    id=pid_key,
                    title=title,
                    url=url,
                    published_at=str(published_at) if published_at else None,
                    authors=authors,
                    summary=summary,
                    tags=tags,
                )
            )
        if len(out) >= max_items:
            break
    return out


def render_digest_md(papers: list[Paper], window_hours: int) -> str:
    ts = _utc_now().strftime("%Y-%m-%d")
    lines = [f"## 文献雷达日报（UTC {ts}，近 {window_hours}h）", ""]
    for p in papers:
        src = "arXiv" if p.source == "arxiv" else "HF Papers"
        lines.append(f"### {p.title}")
        lines.append(f"- 来源：{src}")
        lines.append(f"- 链接：{p.url}")
        if p.published_at:
            lines.append(f"- 发布时间：{p.published_at}")
        if p.authors:
            lines.append(f"- 作者：{', '.join(p.authors[:12])}{'…' if len(p.authors) > 12 else ''}")
        if p.tags:
            lines.append(f"- 标签：{', '.join(p.tags[:12])}{'…' if len(p.tags) > 12 else ''}")
        if p.summary:
            lines.append("")
            lines.append(_norm_space(p.summary))
        lines.append("")
    if len(papers) == 0:
        lines.append("（本时间窗内未抓到匹配结果。可以尝试扩大 `--window-hours` 或放宽 `--query/--keywords`。）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lit-radar")
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--sources", type=str, default="arxiv,hf")
    ap.add_argument(
        "--query",
        type=str,
        default="cat:cs.RO OR cat:cs.AI OR cat:cs.LG",
        help="arXiv search_query (e.g. 'cat:cs.RO AND (dexterous OR tactile)')",
    )
    ap.add_argument("--keywords", type=str, default="", help="comma-separated keywords filter")
    ap.add_argument("--max-results", type=int, default=50, help="max results per source")
    ap.add_argument("--out", type=str, default="out")
    ap.add_argument("--db", type=str, default="")
    args = ap.parse_args(argv)

    sources: list[Source] = []
    for s in (x.strip() for x in args.sources.split(",") if x.strip()):
        if s not in ("arxiv", "hf"):
            raise SystemExit(f"unknown source: {s}")
        sources.append(s)  # type: ignore[arg-type]
    if not sources:
        sources = ["arxiv", "hf"]

    out_dir = args.out
    _ensure_out_dir(out_dir)
    db_path = args.db or os.path.join(out_dir, "lit_radar.sqlite3")
    keywords = _parse_keywords(args.keywords)

    conn = _db_connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.commit()

    fetched: list[Paper] = []
    if "arxiv" in sources:
        fetched.extend(fetch_arxiv(args.window_hours, args.query, max_results=args.max_results))
    if "hf" in sources:
        fetched.extend(fetch_hf_papers(args.window_hours, max_items=args.max_results))

    kept: list[Paper] = []
    for p in fetched:
        if not _keyword_match(p.title, p.summary, keywords):
            continue
        if _db_seen(conn, p):
            continue
        _db_insert(conn, p)
        kept.append(p)
    conn.commit()
    conn.close()

    kept_sorted = sorted(kept, key=lambda x: (x.published_at or "", x.source), reverse=True)
    papers_json_path = os.path.join(out_dir, "papers.json")
    digest_md_path = os.path.join(out_dir, "digest.md")
    with open(papers_json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in kept_sorted], f, ensure_ascii=False, indent=2)
    with open(digest_md_path, "w", encoding="utf-8") as f:
        f.write(render_digest_md(kept_sorted, args.window_hours))

    print(f"saved: {papers_json_path}")
    print(f"saved: {digest_md_path}")
    print(f"new_papers: {len(kept_sorted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

