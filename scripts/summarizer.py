"""Hybrid article summarizer (Gemini / OpenAI API when configured, excerpt fallback otherwise)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

from scripts.config import REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """あなたは沖縄県の宿泊業・観光業担当者向けのニュース編集者です。
以下の記事タイトルと冒頭内容から、実務に役立つポイントを日本語の箇条書き3行（各行35〜55文字程度、先頭は「・」）で簡潔に要約してください。
推測で数値を創作せず、書かれている事実のみを要約してください。

メディア: {source_name}
タイトル: {title}
冒頭抜粋: {excerpt}
"""


def _detect_provider_and_key() -> tuple[str | None, str | None]:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return "gemini", gemini_key

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return "openai", openai_key

    generic_key = os.environ.get("LLM_API_KEY", "").strip()
    if generic_key:
        explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
        if explicit in ("gemini", "openai"):
            return explicit, generic_key
        if generic_key.startswith("AIza"):
            return "gemini", generic_key
        return "openai", generic_key

    return None, None


def _summarize_with_gemini(api_key: str, prompt: str) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 280,
        },
    }
    resp = requests.post(
        endpoint,
        params={"key": api_key},
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(str(p.get("text", "")) for p in parts).strip()
    return _normalize_summary_lines(text)


def _summarize_with_openai(api_key: str, prompt: str) -> str:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    endpoint = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "宿泊・観光業界ニュースを3行で簡潔に要約します。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 280,
    }
    resp = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    text = str(choices[0].get("message", {}).get("content", "")).strip()
    return _normalize_summary_lines(text)


def _normalize_summary_lines(text: str) -> str:
    lines = [re.sub(r"^[-*•・\d.)\s]+", "", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "\n".join(f"・{line}" for line in lines[:3])


def build_fallback_summary(title: str, excerpt: str) -> str:
    """Create a clean excerpt fallback when AI summarization is unavailable."""
    cleaned = re.sub(r"\s+", " ", excerpt or "").strip()
    if cleaned:
        return cleaned
    return f"「{title}」に関する最新記事です。詳細は元記事リンクから確認できます。"


def summarize_article(
    title: str,
    excerpt: str,
    source_name: str,
    allow_ai: bool = True,
) -> tuple[str, str]:
    """Return (summary_text, summary_type) where summary_type is 'ai' or 'excerpt'."""
    if allow_ai:
        provider, api_key = _detect_provider_and_key()
        if provider and api_key:
            prompt = PROMPT_TEMPLATE.format(
                source_name=source_name,
                title=title,
                excerpt=excerpt or "（本文抜粋なし・タイトルのみ）",
            )
            try:
                if provider == "gemini":
                    ai_text = _summarize_with_gemini(api_key, prompt)
                else:
                    ai_text = _summarize_with_openai(api_key, prompt)
                if ai_text:
                    return ai_text, "ai"
            except Exception as exc:  # noqa: BLE001
                logger.warning("AI summarization failed (%s), falling back to excerpt: %s", provider, exc)

    return build_fallback_summary(title, excerpt), "excerpt"
