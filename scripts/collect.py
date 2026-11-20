"""Main collection pipeline: fetch -> deduplicate -> classify -> summarize -> save -> Slack."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.classifier import classify_article
from scripts.config import (
    DATA_FILE,
    DEFAULT_FETCH_LIMIT_PER_SOURCE,
    MAX_STORED_ARTICLES,
    SOURCES,
    TOPICS,
)
from scripts.fetchers import RawArticle, clean_text, fetch_source_articles, normalize_url
from scripts.slack_notify import notify_slack
from scripts.summarizer import summarize_article

JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


def make_article_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def load_existing_data(data_path: Path = DATA_FILE) -> dict[str, Any]:
    if not data_path.exists():
        return {"meta": {}, "articles": []}
    try:
        with data_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("articles"), list):
            return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read existing data (%s), starting fresh: %s", data_path, exc)
    return {"meta": {}, "articles": []}


def _priority_for_ai(article: dict[str, Any]) -> tuple[int, str]:
    topics = article.get("topics") or []
    if "miyako_ishigaki" in topics:
        rank = 0
    elif "okinawa" in topics:
        rank = 1
    elif "dx" in topics:
        rank = 2
    else:
        rank = 3
    return (rank, article.get("published_at", ""))


def run_collection(
    data_path: Path = DATA_FILE,
    limit_per_source: int = DEFAULT_FETCH_LIMIT_PER_SOURCE,
    skip_notify: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute full collection run and return updated dataset."""
    existing = load_existing_data(data_path)
    existing_articles: list[dict[str, Any]] = existing.get("articles") or []
    # Drop sample seed items on first real successful collection
    has_real_articles = any(not a.get("is_seed") for a in existing_articles)
    existing_by_url: dict[str, dict[str, Any]] = {
        normalize_url(a["url"]): a
        for a in existing_articles
        if a.get("url") and not a.get("is_seed")
    }

    now_iso = datetime.now(JST).isoformat()
    source_statuses: list[dict[str, Any]] = []
    fetched_raw: list[RawArticle] = []

    for source in SOURCES:
        try:
            items, method = fetch_source_articles(source, limit=limit_per_source)
            fetched_raw.extend(items)
            source_statuses.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "url": source.url,
                    "status": "ok",
                    "fetched_count": len(items),
                    "method": method,
                    "checked_at": now_iso,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Fetch failed: %s", source.name, exc)
            source_statuses.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "url": source.url,
                    "status": "error",
                    "fetched_count": 0,
                    "error": str(exc),
                    "checked_at": now_iso,
                }
            )

    if not fetched_raw and not has_real_articles:
        logger.warning("No articles fetched from any source; keeping existing dataset unchanged.")
        return existing

    # Deduplicate newly fetched items against existing store and within current batch
    new_candidates: list[dict[str, Any]] = []
    seen_batch: set[str] = set()

    for raw in fetched_raw:
        norm_url = normalize_url(raw.url)
        if norm_url in existing_by_url or norm_url in seen_batch:
            continue
        seen_batch.add(norm_url)

        topics, matched_keywords = classify_article(
            title=raw.title,
            summary=raw.excerpt,
            tags=raw.tags,
            url=norm_url,
        )
        new_candidates.append(
            {
                "id": make_article_id(norm_url),
                "source_id": raw.source_id,
                "source_name": raw.source_name,
                "title": raw.title,
                "url": norm_url,
                "published_at": raw.published_at,
                "collected_at": now_iso,
                "excerpt": raw.excerpt,
                "summary": "",
                "summary_type": "excerpt",
                "topics": topics,
                "matched_keywords": matched_keywords,
                "tags": raw.tags,
                "image_url": raw.image_url,
            }
        )

    # Prioritize Okinawa / Miyako-Ishigaki / DX articles when AI summary budget is bounded
    max_ai = int(os.environ.get("MAX_AI_SUMMARIES_PER_RUN", "15"))
    new_candidates.sort(key=lambda a: (_priority_for_ai(a)[0], a["published_at"]))
    # Within each priority tier, newest first
    prioritized: list[dict[str, Any]] = []
    for rank in range(4):
        tier = [a for a in new_candidates if _priority_for_ai(a)[0] == rank]
        tier.sort(key=lambda a: a["published_at"], reverse=True)
        prioritized.extend(tier)

    ai_used = 0
    for article in prioritized:
        allow_ai = ai_used < max_ai
        summary, summary_type = summarize_article(
            title=article["title"],
            excerpt=article["excerpt"],
            source_name=article["source_name"],
            allow_ai=allow_ai,
        )
        article["summary"] = summary
        article["summary_type"] = summary_type
        if summary_type == "ai":
            ai_used += 1

    # Re-classify and re-clean existing articles so rule improvements propagate automatically
    merged_map: dict[str, dict[str, Any]] = dict(existing_by_url)
    for url_key, existing_item in merged_map.items():
        if existing_item.get("excerpt"):
            cleaned_excerpt = clean_text(existing_item["excerpt"], max_len=280, strip_boilerplate=True)
            existing_item["excerpt"] = cleaned_excerpt
            if existing_item.get("summary_type") != "ai":
                existing_item["summary"] = cleaned_excerpt
        topics, matched_keywords = classify_article(
            title=existing_item.get("title", ""),
            summary=existing_item.get("excerpt") or existing_item.get("summary", ""),
            tags=existing_item.get("tags") or [],
            url=url_key,
        )
        existing_item["topics"] = topics
        existing_item["matched_keywords"] = matched_keywords

    for new_item in prioritized:
        merged_map[new_item["url"]] = new_item

    merged_articles = sorted(
        merged_map.values(),
        key=lambda a: (a.get("published_at", ""), a.get("collected_at", "")),
        reverse=True,
    )[:MAX_STORED_ARTICLES]

    topic_counts = {
        topic.id: sum(1 for a in merged_articles if topic.id in (a.get("topics") or []))
        for topic in TOPICS
    }

    dataset: dict[str, Any] = {
        "meta": {
            "updated_at": now_iso,
            "total_articles": len(merged_articles),
            "new_articles_last_run": len(prioritized),
            "ai_summaries_last_run": ai_used,
            "topic_counts": topic_counts,
            "topics": [
                {
                    "id": t.id,
                    "label": t.label,
                    "short_label": t.short_label,
                    "description": t.description,
                }
                for t in TOPICS
            ],
            "sources": source_statuses,
        },
        "articles": merged_articles,
    }

    if not dry_run:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        with data_path.open("w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info(
            "Saved %d total articles (%d new) to %s",
            len(merged_articles),
            len(prioritized),
            data_path,
        )

    if not skip_notify and not dry_run:
        notify_slack(prioritized)

    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect travel & hotel industry news.")
    parser.add_argument("--limit", type=int, default=DEFAULT_FETCH_LIMIT_PER_SOURCE)
    parser.add_argument("--skip-notify", action="store_true", help="Skip Slack notification")
    parser.add_argument("--dry-run", action="store_true", help="Do not write JSON or notify")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = run_collection(
        limit_per_source=args.limit,
        skip_notify=args.skip_notify,
        dry_run=args.dry_run,
    )
    meta = result.get("meta", {})
    logger.info(
        "Done. Total=%s, New=%s, TopicCounts=%s",
        meta.get("total_articles"),
        meta.get("new_articles_last_run"),
        meta.get("topic_counts"),
    )


if __name__ == "__main__":
    main()
