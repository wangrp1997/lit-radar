from __future__ import annotations

import argparse

from .config import resolve_settings, load_config
from .pipeline import run_pipeline
from .profiles import DEFAULT_PROFILES, merge_profiles, parse_profiles_from_config


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
    ap.add_argument("--llm-config", dest="llm_config", type=str, default=None, help="path to local LLM config JSON")
    args = ap.parse_args(argv)

    cfg: dict = load_config(args.config) if args.config else {}
    settings = resolve_settings(args, cfg)
    profiles = merge_profiles(DEFAULT_PROFILES, parse_profiles_from_config(cfg))
    if settings.profile not in profiles:
        known = ", ".join(sorted(profiles.keys()))
        raise SystemExit(f"unknown profile: {settings.profile} (known: {known})")
    profile_terms = profiles[settings.profile]
    return run_pipeline(settings, profile_terms)


if __name__ == "__main__":
    raise SystemExit(main())

