"""Slack Incoming Webhook notifier with topic prioritization and Block Kit formatting."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from scripts.config import REQUEST_TIMEOUT_SECONDS, TOPIC_MAP

logger = logging.getLogger(__name__)

TOPIC_EMOJI = {
    "miyako_ishigaki": "🏝️",
    "okinawa": "🌺",
    "dx": "💻",
}


def _topic_priority(article: dict[str, Any]) -> tuple[int, str]:
    topics = article.get("topics") or []
    if "miyako_ishigaki" in topics:
        rank = 0
    elif "okinawa" in topics:
        rank = 1
    elif "dx" in topics:
        rank = 2
    else:
        rank = 3
    # Sort newest first inside each priority tier (negated string handled separately)
    return (rank, article.get("published_at", ""))


def build_slack_payload(
    articles: list[dict[str, Any]],
    site_url: str = "",
    max_items: int = 15,
) -> dict[str, Any]:
    """Build a Slack Block Kit payload summarizing newly collected articles."""
    sorted_articles = sorted(
        articles,
        key=lambda a: (_topic_priority(a)[0], a.get("published_at", "")),
    )
    # Keep newest first within each priority rank
    grouped: list[dict[str, Any]] = []
    for rank in range(4):
        tier = [a for a in sorted_articles if _topic_priority(a)[0] == rank]
        tier.sort(key=lambda a: a.get("published_at", ""), reverse=True)
        grouped.extend(tier)

    counts = {
        "miyako_ishigaki": sum(1 for a in grouped if "miyako_ishigaki" in (a.get("topics") or [])),
        "okinawa": sum(1 for a in grouped if "okinawa" in (a.get("topics") or [])),
        "dx": sum(1 for a in grouped if "dx" in (a.get("topics") or [])),
    }

    summary_parts = [f"全 *{len(grouped)}件*"]
    if counts["miyako_ishigaki"]:
        summary_parts.append(f"🏝️ 宮古・石垣 *{counts['miyako_ishigaki']}件*")
    if counts["okinawa"]:
        summary_parts.append(f"🌺 沖縄関連 *{counts['okinawa']}件*")
    if counts["dx"]:
        summary_parts.append(f"💻 DX関連 *{counts['dx']}件*")

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📰 宿泊・観光ニュース新着まとめ（{len(grouped)}件）",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": " ｜ ".join(summary_parts),
                }
            ],
        },
        {"type": "divider"},
    ]

    displayed = grouped[:max_items]
    for article in displayed:
        title = str(article.get("title", "タイトルなし")).replace("<", "＜").replace(">", "＞")
        url = str(article.get("url", ""))
        source_name = str(article.get("source_name", ""))
        summary = str(article.get("summary", "")).strip()
        if len(summary) > 180:
            summary = summary[:179].rstrip() + "…"

        badges = []
        for tid in article.get("topics") or []:
            topic = TOPIC_MAP.get(tid)
            if topic:
                badges.append(f"{TOPIC_EMOJI.get(tid, '🏷️')}{topic.short_label}")
        badge_str = f"  `{'` `'.join(badges)}`" if badges else ""
        ai_mark = " ✨AI要約" if article.get("summary_type") == "ai" else ""

        text = f"*<{url}|{title}>*\n_{source_name}_{ai_mark}{badge_str}"
        if summary:
            text += f"\n{summary}"

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        )

    remaining = len(grouped) - len(displayed)
    footer_lines: list[str] = []
    if remaining > 0:
        footer_lines.append(f"ほか *{remaining}件* の新着記事があります。")
    if site_url:
        footer_lines.append(f"<{site_url}|個人用ニュースサイトで一覧・フィルターを見る →>")

    if footer_lines:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " ".join(footer_lines)}],
            }
        )

    fallback_text = f"宿泊・観光ニュース新着 {len(grouped)}件: " + " / ".join(
        str(a.get("title", "")) for a in displayed[:3]
    )
    return {"text": fallback_text, "blocks": blocks}


def notify_slack(articles: list[dict[str, Any]]) -> bool:
    """Send new articles to Slack via Incoming Webhook.

    Returns True if a message was sent, False if skipped.
    """
    if not articles:
        logger.info("No new articles to notify.")
        return False

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.info("SLACK_WEBHOOK_URL is not configured; skipping Slack notification.")
        return False

    notify_filter = os.environ.get("SLACK_NOTIFY_FILTER", "all").strip().lower()
    target_articles = articles
    if notify_filter == "topics":
        target_articles = [a for a in articles if a.get("topics")]
        if not target_articles:
            logger.info("No topic-matched articles to notify (SLACK_NOTIFY_FILTER=topics).")
            return False

    site_url = os.environ.get("SITE_URL", "").strip()
    max_items = int(os.environ.get("SLACK_MAX_ITEMS", "15"))
    payload = build_slack_payload(target_articles, site_url=site_url, max_items=max_items)

    resp = requests.post(
        webhook_url,
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack通知に失敗しました: HTTP {resp.status_code} {resp.text}")

    logger.info("Sent Slack notification for %d articles.", len(target_articles))
    return True
