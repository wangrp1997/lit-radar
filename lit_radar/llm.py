from __future__ import annotations

import json
import time

import requests

from .models import ScoredPaper
from .utils import norm_space


def _extract_usage(data: dict) -> dict[str, int]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def load_llm_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"llm config must be a JSON object: {path}")
    return data


def llm_summaries_for_zh(
    papers: list[ScoredPaper],
    *,
    llm_cfg: dict,
    timeout_seconds: float,
    retries: int,
    verbose: bool,
) -> tuple[dict[str, str], dict[str, int]]:
    api_key = str(llm_cfg.get("api_key") or "").strip()
    model = str(llm_cfg.get("model") or "").strip()
    base_url = str(llm_cfg.get("base_url") or "").rstrip("/")
    top_n = int(llm_cfg.get("top_n") or 10)
    if not api_key or not model or not base_url:
        if verbose:
            print("llm: missing api_key/model/base_url, skip LLM summaries")
        return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    if not papers:
        return ({}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    endpoint = f"{base_url}/chat/completions"
    out: dict[str, str] = {}
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for p in papers[: max(0, top_n)]:
        user_text = (
            f"标题: {p.title}\n\n"
            f"摘要: {p.summary or ''}\n\n"
            "请只用中文输出以下四行，不要添加其他内容：\n"
            "问题: <一句话>\n"
            "方法: <一句话>\n"
            "结果: <一句话>\n"
            "与灵巧手相关性: <一句话>"
        )
        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "你是机器人论文分析助手，回答必须简洁、客观。"},
                {"role": "user", "content": user_text},
            ],
        }
        summary = ""
        for attempt in range(max(1, retries)):
            try:
                r = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout_seconds,
                )
                r.raise_for_status()
                data = r.json()
                u = _extract_usage(data)
                usage_total["prompt_tokens"] += u["prompt_tokens"]
                usage_total["completion_tokens"] += u["completion_tokens"]
                usage_total["total_tokens"] += u["total_tokens"]
                if verbose:
                    print(
                        f"llm usage: id={p.id} prompt={u['prompt_tokens']} "
                        f"completion={u['completion_tokens']} total={u['total_tokens']}"
                    )
                summary = norm_space(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
                break
            except Exception:
                if attempt < max(1, retries) - 1:
                    time.sleep(1.2 * (attempt + 1))
                    continue
        if summary:
            out[p.id] = summary
    if verbose:
        print(f"llm: using model={model} summarized={len(out)}/{min(len(papers), max(0, top_n))}")
        print(
            "llm usage total: "
            f"prompt={usage_total['prompt_tokens']} "
            f"completion={usage_total['completion_tokens']} "
            f"total={usage_total['total_tokens']}"
        )
    return (out, usage_total)

