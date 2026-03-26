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
from requests.exceptions import RequestException

from .config import Settings, load_config, resolve_settings
from .profiles import DEFAULT_PROFILES, merge_profiles, parse_profiles_from_config, score_text


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


def _exclude_match(title: str, summary: str | None, exclude: list[str]) -> bool:
    """True if any exclude phrase appears (case-insensitive)."""
    if not exclude:
        return False
    hay = (title + "\n" + (summary or "")).lower()
    return any(k in hay for k in exclude)


def _to_scored(p: Paper, profile_terms) -> ScoredPaper:
    score, matched_terms = score_text(p.title + "\n" + (p.summary or ""), profile_terms)
    return ScoredPaper(
        source=p.source,
        id=p.id,
        title=p.title,
        url=p.url,
        published_at=p.published_at,
        authors=p.authors,
        summary=p.summary,
        tags=p.tags,
        score=score,
        matched_terms=matched_terms,
    )


def _translate_to_zh(text: str, cache: dict[str, str]) -> str:
    raw = _norm_space(text)
    if not raw:
        return raw
    if raw in cache:
        return cache[raw]
    try:
        from deep_translator import GoogleTranslator  # lazy import for optional dependency

        translated = GoogleTranslator(source="auto", target="zh-CN").translate(raw)
        out = _norm_space(translated or raw)
    except Exception:
        out = raw
    cache[raw] = out
    return out


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


def _get_with_retry(url: str, *, params: dict | None, timeout_seconds: float, retries: int) -> requests.Response:
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


def fetch_arxiv(window_hours: int, query: str, max_results: int, *, timeout_seconds: float, retries: int) -> list[Paper]:
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
    r = _get_with_retry(base, params=params, timeout_seconds=timeout_seconds, retries=retries)
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


def fetch_hf_papers(window_hours: int, max_items: int, *, timeout_seconds: float, retries: int) -> list[Paper]:
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
        r = _get_with_retry(url, params={"date": d.isoformat()}, timeout_seconds=timeout_seconds, retries=retries)
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


def render_digest_md(
    papers: list[ScoredPaper],
    window_hours: int,
    profile: str,
    lang: str = "en",
    translate_summary_zh: bool = True,
) -> str:
    ts = _utc_now().strftime("%Y-%m-%d")
    prof = profile.replace("_", " ")
    is_zh = lang == "zh"
    zh_cache: dict[str, str] = {}
    if is_zh:
        lines = [f"## 文献雷达日报（UTC {ts}，近 {window_hours}h，profile: {prof}）", ""]
    else:
        lines = [f"## Literature Radar Digest (UTC {ts}, last {window_hours}h, profile: {prof})", ""]
    for p in papers:
        src = "arXiv" if p.source == "arxiv" else "HF Papers"
        lines.append(f"### {p.title}")
        lines.append(f"- {'来源' if is_zh else 'Source'}: {src}")
        lines.append(f"- {'链接' if is_zh else 'URL'}: {p.url}")
        lines.append(f"- {'相关度' if is_zh else 'Score'}: {p.score:.1f}")
        if p.matched_terms:
            lines.append(
                f"- {'命中' if is_zh else 'Matched terms'}: "
                f"{', '.join(p.matched_terms[:16])}{'…' if len(p.matched_terms) > 16 else ''}"
            )
        if p.published_at:
            lines.append(f"- {'发布时间' if is_zh else 'Published at'}: {p.published_at}")
        if p.authors:
            lines.append(f"- {'作者' if is_zh else 'Authors'}: {', '.join(p.authors[:12])}{'…' if len(p.authors) > 12 else ''}")
        if p.tags:
            lines.append(f"- {'标签' if is_zh else 'Tags'}: {', '.join(p.tags[:12])}{'…' if len(p.tags) > 12 else ''}")
        if p.summary:
            lines.append("")
            summary = _norm_space(p.summary)
            if is_zh and translate_summary_zh:
                summary = _translate_to_zh(summary, zh_cache)
            lines.append(summary)
        lines.append("")
    if len(papers) == 0:
        if is_zh:
            lines.append("（本时间窗内未抓到匹配结果。可以尝试扩大 `--window-hours` 或放宽 `--query/--keywords`。）")
        else:
            lines.append("(No matching papers found in this time window. Try increasing --window-hours or relaxing --query/--keywords.)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lit-radar")
    ap.add_argument("--config", type=str, default="", help="path to JSON config file")
    ap.add_argument("--window-hours", type=int, default=None)
    ap.add_argument("--sources", type=str, default=None)
    ap.add_argument(
        "--query",
        type=str,
        default=None,
        help="arXiv search_query (e.g. 'cat:cs.RO AND (dexterous OR tactile)')",
    )
    ap.add_argument("--keywords", type=str, default=None, help="comma-separated keywords filter")
    ap.add_argument(
        "--require-any-keywords",
        dest="require_any_keywords",
        type=str,
        default=None,
        help="comma-separated: title/abstract must contain at least one (hand-focus gate)",
    )
    ap.add_argument(
        "--exclude-keywords",
        dest="exclude_keywords",
        type=str,
        default=None,
        help="comma-separated: drop if title/abstract contains any",
    )
    ap.add_argument("--max-results", type=int, default=None, help="max results per source")
    ap.add_argument("--profile", type=str, default=None, help="scoring profile: general | dexterous_hand")
    ap.add_argument("--min-score", type=float, default=None, help="minimum relevance score to keep")
    ap.add_argument(
        "--include-seen",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="also output papers already in DB (omit flag to use config default; --no-include-seen to force off)",
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--translate-summary-zh", dest="translate_summary_zh", action="store_true", default=None)
    grp.add_argument("--no-translate-summary-zh", dest="translate_summary_zh", action="store_false", default=None)
    ap.add_argument("--timeout-seconds", dest="timeout_seconds", type=float, default=None, help="HTTP timeout seconds")
    ap.add_argument("--retries", type=int, default=None, help="HTTP retry attempts")
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--db", type=str, default=None)
    ap.add_argument("--verbose", "-v", action="store_true", default=None, help="print filter stage counts")
    args = ap.parse_args(argv)

    cfg: dict = load_config(args.config) if args.config else {}
    settings: Settings = resolve_settings(args, cfg)
    profiles = merge_profiles(DEFAULT_PROFILES, parse_profiles_from_config(cfg))
    if settings.profile not in profiles:
        known = ", ".join(sorted(profiles.keys()))
        raise SystemExit(f"unknown profile: {settings.profile} (known: {known})")
    profile_terms = profiles[settings.profile]

    sources: list[Source] = []
    for s in (x.strip() for x in settings.sources.split(",") if x.strip()):
        if s not in ("arxiv", "hf"):
            raise SystemExit(f"unknown source: {s}")
        sources.append(s)  # type: ignore[arg-type]
    if not sources:
        sources = ["arxiv", "hf"]

    _ensure_out_dir(settings.out)
    db_path = (str(settings.db).strip() if settings.db else "") or os.path.join(settings.out, "lit_radar.sqlite3")
    keywords = _parse_keywords(settings.keywords)
    require_any = _parse_keywords(settings.require_any_keywords)
    exclude = _parse_keywords(settings.exclude_keywords)

    conn = _db_connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.commit()

    fetched: list[Paper] = []
    if "arxiv" in sources:
        fetched.extend(
            fetch_arxiv(
                settings.window_hours,
                settings.query,
                max_results=settings.max_results,
                timeout_seconds=settings.timeout_seconds,
                retries=settings.retries,
            )
        )
    if "hf" in sources:
        fetched.extend(
            fetch_hf_papers(
                settings.window_hours,
                max_items=settings.max_results,
                timeout_seconds=settings.timeout_seconds,
                retries=settings.retries,
            )
        )

    kept: list[Paper] = []
    drop_req = drop_excl = drop_kw = 0
    for p in fetched:
        if require_any and not _keyword_match(p.title, p.summary, require_any):
            drop_req += 1
            continue
        if _exclude_match(p.title, p.summary, exclude):
            drop_excl += 1
            continue
        if not _keyword_match(p.title, p.summary, keywords):
            drop_kw += 1
            continue
        seen = _db_seen(conn, p)
        if not seen:
            _db_insert(conn, p)
        if (not seen) or settings.include_seen:
            kept.append(p)
    conn.commit()
    conn.close()

    scored = [_to_scored(p, profile_terms) for p in kept]
    below_min = sum(1 for p in scored if p.score < settings.min_score)
    scored = [p for p in scored if p.score >= settings.min_score]
    kept_sorted = sorted(scored, key=lambda x: (x.score, x.published_at or "", x.source), reverse=True)
    papers_json_path = os.path.join(settings.out, "papers.json")
    digest_md_path = os.path.join(settings.out, "digest.md")
    digest_zh_md_path = os.path.join(settings.out, "digest.zh.md")
    with open(papers_json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in kept_sorted], f, ensure_ascii=False, indent=2)
    with open(digest_md_path, "w", encoding="utf-8") as f:
        f.write(render_digest_md(kept_sorted, settings.window_hours, settings.profile, lang="en"))
    with open(digest_zh_md_path, "w", encoding="utf-8") as f:
        f.write(
            render_digest_md(
                kept_sorted,
                settings.window_hours,
                settings.profile,
                lang="zh",
                translate_summary_zh=settings.translate_summary_zh,
            )
        )

    print(f"saved: {papers_json_path}")
    print(f"saved: {digest_md_path}")
    print(f"saved: {digest_zh_md_path}")
    print(f"papers_out: {len(kept_sorted)}")
    if settings.verbose:
        pass_req = len(fetched) - drop_req
        print(
            "stats: "
            f"fetched={len(fetched)} "
            f"pass_require_any={pass_req} "
            f"drop_require_any={drop_req} "
            f"drop_exclude={drop_excl} "
            f"drop_keywords={drop_kw} "
            f"kept_after_filters={len(kept)} "
            f"drop_below_min_score={below_min} "
            f"min_score={settings.min_score} "
            f"include_seen={settings.include_seen}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

