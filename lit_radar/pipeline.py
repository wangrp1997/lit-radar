from __future__ import annotations

import json
import os
from dataclasses import asdict

from .config import Settings
from .db import db_connect, db_insert, db_seen
from .llm import llm_summaries_for_zh, load_llm_config
from .models import Paper, ScoredPaper
from .profiles import score_text
from .render import render_digest_md
from .sources import fetch_arxiv, fetch_hf_papers
from .utils import ensure_out_dir, exclude_match, keyword_match, parse_keywords


def to_scored(p: Paper, profile_terms) -> ScoredPaper:
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


def run_pipeline(settings: Settings, profile_terms) -> int:
    ensure_out_dir(settings.out)
    db_path = (str(settings.db).strip() if settings.db else "") or os.path.join(settings.out, "lit_radar.sqlite3")
    keywords = parse_keywords(settings.keywords)
    require_any = parse_keywords(settings.require_any_keywords)
    exclude = parse_keywords(settings.exclude_keywords)

    conn = db_connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.commit()

    fetched: list[Paper] = []
    if "arxiv" in settings.sources:
        fetched.extend(
            fetch_arxiv(
                settings.window_hours,
                settings.query,
                max_results=settings.max_results,
                timeout_seconds=settings.timeout_seconds,
                retries=settings.retries,
            )
        )
    if "hf" in settings.sources:
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
        if require_any and not keyword_match(p.title, p.summary, require_any):
            drop_req += 1
            continue
        if exclude_match(p.title, p.summary, exclude):
            drop_excl += 1
            continue
        if not keyword_match(p.title, p.summary, keywords):
            drop_kw += 1
            continue
        seen = db_seen(conn, p)
        if not seen:
            db_insert(conn, p)
        if (not seen) or settings.include_seen:
            kept.append(p)
    conn.commit()
    conn.close()

    scored = [to_scored(p, profile_terms) for p in kept]
    below_min = sum(1 for p in scored if p.score < settings.min_score)
    scored = [p for p in scored if p.score >= settings.min_score]
    kept_sorted = sorted(scored, key=lambda x: (x.score, x.published_at or "", x.source), reverse=True)
    llm_notes: dict[str, str] = {}
    llm_usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if settings.llm_config:
        try:
            llm_cfg = load_llm_config(settings.llm_config)
            llm_notes, llm_usage_total = llm_summaries_for_zh(
                kept_sorted,
                llm_cfg=llm_cfg,
                timeout_seconds=settings.timeout_seconds,
                retries=settings.retries,
                verbose=settings.verbose,
            )
        except Exception as e:
            if settings.verbose:
                print(f"llm: failed to load/use config ({e}); continue without LLM summaries")

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
                llm_notes=llm_notes,
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
        if settings.llm_config:
            print(
                "llm usage total: "
                f"prompt={llm_usage_total['prompt_tokens']} "
                f"completion={llm_usage_total['completion_tokens']} "
                f"total={llm_usage_total['total_tokens']}"
            )
    return 0

