"""Topic classifier for Okinawa, DX, and Miyako/Ishigaki filtering."""

from __future__ import annotations

import re
from typing import Iterable

from scripts.config import TOPICS, TopicDefinition


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _matches_topic(text: str, topic: TopicDefinition) -> list[str]:
    if not text:
        return []

    if topic.exclude_if_contains:
        for excluded in topic.exclude_if_contains:
            if excluded.lower() in text:
                return []

    matched: list[str] = []
    for kw in topic.substring_keywords:
        if kw.lower() in text:
            matched.append(kw)

    for kw in topic.word_keywords:
        pattern = rf"(?<![a-z0-9]){re.escape(kw.lower())}(?![a-z0-9])"
        if re.search(pattern, text):
            matched.append(kw.upper())

    return matched


def classify_article(
    title: str,
    summary: str = "",
    tags: Iterable[str] = (),
    url: str = "",
) -> tuple[list[str], list[str]]:
    """Return (topic_ids, matched_keywords) for an article.

    Articles tagged with `miyako_ishigaki` also receive `okinawa` because
    Miyakojima and Ishigakijima are part of Okinawa Prefecture.
    """
    combined = _normalize(" ".join([title, summary, " ".join(tags), url]))
    found_topics: list[str] = []
    matched_keywords: list[str] = []

    for topic in TOPICS:
        hits = _matches_topic(combined, topic)
        if hits:
            found_topics.append(topic.id)
            for hit in hits:
                if hit not in matched_keywords:
                    matched_keywords.append(hit)

    if "miyako_ishigaki" in found_topics and "okinawa" not in found_topics:
        found_topics.append("okinawa")

    # Consistent display priority: miyako_ishigaki -> okinawa -> dx
    order = {t.id: idx for idx, t in enumerate(TOPICS)}
    found_topics.sort(key=lambda tid: order.get(tid, 99))
    return found_topics, matched_keywords[:8]
