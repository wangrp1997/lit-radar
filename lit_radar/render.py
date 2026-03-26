from __future__ import annotations

from .models import ScoredPaper
from .utils import norm_space, utc_now


def _translate_to_zh(text: str, cache: dict[str, str]) -> str:
    raw = norm_space(text)
    if not raw:
        return raw
    if raw in cache:
        return cache[raw]
    try:
        from deep_translator import GoogleTranslator

        translated = GoogleTranslator(source="auto", target="zh-CN").translate(raw)
        out = norm_space(translated or raw)
    except Exception:
        out = raw
    cache[raw] = out
    return out


def render_digest_md(
    papers: list[ScoredPaper],
    window_hours: int,
    profile: str,
    lang: str = "en",
    translate_summary_zh: bool = True,
    llm_notes: dict[str, str] | None = None,
) -> str:
    ts = utc_now().strftime("%Y-%m-%d")
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
        if is_zh and llm_notes and p.id in llm_notes:
            lines.append("- 系统总结:")
            lines.append("")
            lines.append(llm_notes[p.id])
        if p.summary:
            lines.append("")
            summary = norm_space(p.summary)
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

