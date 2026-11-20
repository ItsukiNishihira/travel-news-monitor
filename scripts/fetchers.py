"""Multi-strategy fetchers (RSS, WordPress REST API, HTML fallback) for target sites."""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from scripts.config import (
    DEFAULT_FETCH_LIMIT_PER_SOURCE,
    REQUEST_TIMEOUT_SECONDS,
    SourceConfig,
    USER_AGENT,
)

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

DATE_PATTERNS = (
    re.compile(r"(20\d{2})\s*[./年-]\s*(\d{1,2})\s*[./月-]\s*(\d{1,2})"),
    re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/"),
    re.compile(r"/(20\d{2})(\d{2})(\d{2})-\d+"),
)


@dataclass
class RawArticle:
    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)
    image_url: str = ""


def normalize_url(url: str) -> str:
    """Normalize article URL for reliable deduplication."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


_CJK_CHARS = r"\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff\uff01-\uff60"
_JP_OPEN = r"「『（【［〈《"
_JP_CLOSE = r"」』）】］〉》、。・！？："
_BLOCK_TAGS = ("p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote")
_SHORTCODE_RE = re.compile(r"\[/?[A-Za-z][A-Za-z0-9_=-]*(?:\s+[^\]]*)?\]|\[/?[A-Za-z][A-Za-z0-9_=-]*$")
_BOILERPLATE_RE = re.compile(r"(?:関連記事\s*[:：]|(?:^|[\s。！？])目次(?:\s|$))")


def _html_to_plain_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        if tag.name == "br":
            tag.replace_with(" ")
        else:
            tag.append(" ")
    return soup.get_text("")


def clean_text(raw: str, max_len: int = 280, strip_boilerplate: bool = False) -> str:
    """Strip HTML tags, CMS shortcodes, and unnatural spaces around Japanese characters."""
    if not raw:
        return ""
    text = raw
    if "<" in text and ">" in text:
        text = _html_to_plain_text(text)
    text = html.unescape(text)
    text = _SHORTCODE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()

    if strip_boilerplate:
        m = _BOILERPLATE_RE.search(text)
        if m and m.start() >= 40:
            # Keep sentence-ending punctuation if it was matched right before "目次"
            cut_pos = m.start() + 1 if text[m.start()] in "。！？" else m.start()
            text = text[:cut_pos].rstrip(" 、・")

    # Remove unnatural spaces inserted around Japanese characters/punctuation
    # while preserving spaces between Latin words (e.g., "World Travel Awards").
    text = re.sub(rf"(?<=[{_JP_OPEN}]) ", "", text)
    text = re.sub(rf" (?=[{_JP_CLOSE}])", "", text)
    text = re.sub(rf"(?<=[{_CJK_CHARS}]) (?=[{_CJK_CHARS}])", "", text)
    text = re.sub(rf"(?<=[{_CJK_CHARS}]) (?=[A-Za-z0-9])", "", text)
    text = re.sub(rf"(?<=[A-Za-z0-9]) (?=[{_CJK_CHARS}])", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def parse_date_to_iso(value: str | None, fallback_url: str = "") -> str:
    """Parse various date representations (RFC2822, ISO, Japanese dates, URL) to ISO-8601 JST."""
    candidates = [value or "", fallback_url]
    for candidate in candidates:
        if not candidate:
            continue
        # Try explicit regex first for Japanese / dot / URL formats
        for pattern in DATE_PATTERNS:
            m = pattern.search(candidate)
            if m:
                try:
                    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    dt = datetime(year, month, day, 9, 0, tzinfo=JST)
                    return dt.isoformat()
                except ValueError:
                    continue
        # Fallback to dateutil for RFC2822 / ISO strings
        if candidate is value:
            try:
                dt = date_parser.parse(candidate)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                else:
                    dt = dt.astimezone(JST)
                return dt.isoformat()
            except (ValueError, TypeError, OverflowError):
                continue

    return datetime.now(JST).isoformat()


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        }
    )
    return session


def _extract_feed_image(entry: Any) -> str:
    media_content = entry.get("media_content") or []
    if media_content and isinstance(media_content, list):
        url = media_content[0].get("url")
        if url:
            return str(url)
    media_thumb = entry.get("media_thumbnail") or []
    if media_thumb and isinstance(media_thumb, list):
        url = media_thumb[0].get("url")
        if url:
            return str(url)
    for link in entry.get("links") or []:
        if str(link.get("type", "")).startswith("image/"):
            return str(link.get("href", ""))
    return ""


def parse_rss_content(xml_content: bytes | str, source: SourceConfig, limit: int) -> list[RawArticle]:
    """Parse RSS/Atom XML into RawArticle entries."""
    parsed = feedparser.parse(xml_content)
    entries = parsed.get("entries") or []
    articles: list[RawArticle] = []
    seen: set[str] = set()

    for entry in entries:
        link = entry.get("link") or ""
        title = clean_text(entry.get("title") or "", max_len=200)
        if not link or not title:
            continue
        norm_url = normalize_url(urljoin(source.url, link))
        if norm_url in seen:
            continue
        seen.add(norm_url)

        date_raw = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("dc_date")
            or ""
        )
        published_at = parse_date_to_iso(date_raw, fallback_url=norm_url)

        raw_summary = entry.get("summary") or entry.get("description") or ""
        if not raw_summary and entry.get("content"):
            raw_summary = entry["content"][0].get("value", "")
        excerpt = clean_text(raw_summary, max_len=280, strip_boilerplate=True)

        tags = [
            clean_text(t.get("term", ""), max_len=40)
            for t in (entry.get("tags") or [])
            if t.get("term")
        ]
        image_url = _extract_feed_image(entry)

        articles.append(
            RawArticle(
                source_id=source.id,
                source_name=source.name,
                title=title,
                url=norm_url,
                published_at=published_at,
                excerpt=excerpt,
                tags=tags[:6],
                image_url=image_url,
            )
        )
        if len(articles) >= limit:
            break

    return articles


def parse_wp_api_posts(posts: list[dict[str, Any]], source: SourceConfig, limit: int) -> list[RawArticle]:
    """Parse WordPress REST API posts JSON into RawArticle entries."""
    articles: list[RawArticle] = []
    seen: set[str] = set()

    for post in posts:
        link = post.get("link") or ""
        title_obj = post.get("title") or {}
        title = clean_text(title_obj.get("rendered", "") if isinstance(title_obj, dict) else str(title_obj), max_len=200)
        if not link or not title:
            continue
        norm_url = normalize_url(link)
        if norm_url in seen:
            continue
        seen.add(norm_url)

        excerpt_obj = post.get("excerpt") or {}
        excerpt = clean_text(
            excerpt_obj.get("rendered", "") if isinstance(excerpt_obj, dict) else str(excerpt_obj),
            max_len=280,
            strip_boilerplate=True,
        )
        published_at = parse_date_to_iso(post.get("date") or post.get("modified"), fallback_url=norm_url)

        tags: list[str] = []
        image_url = ""
        embedded = post.get("_embedded") or {}
        for term_group in embedded.get("wp:term") or []:
            if isinstance(term_group, list):
                for term in term_group:
                    name = clean_text(term.get("name", ""), max_len=40)
                    if name and name not in tags:
                        tags.append(name)
        featured = embedded.get("wp:featuredmedia") or []
        if featured and isinstance(featured, list):
            image_url = str(featured[0].get("source_url") or "")

        articles.append(
            RawArticle(
                source_id=source.id,
                source_name=source.name,
                title=title,
                url=norm_url,
                published_at=published_at,
                excerpt=excerpt,
                tags=tags[:6],
                image_url=image_url,
            )
        )
        if len(articles) >= limit:
            break

    return articles


def discover_feed_urls(html_text: str, base_url: str) -> list[str]:
    """Find RSS/Atom feed links advertised in HTML <head> or body."""
    soup = BeautifulSoup(html_text, "html.parser")
    discovered: list[str] = []

    for link in soup.find_all("link", attrs={"rel": lambda r: r and "alternate" in " ".join(r).lower() if isinstance(r, list) else (r and "alternate" in r.lower())}):
        link_type = (link.get("type") or "").lower()
        href = link.get("href")
        if href and ("rss" in link_type or "atom" in link_type or "xml" in link_type):
            full_url = urljoin(base_url, href)
            if full_url not in discovered:
                discovered.append(full_url)

    for anchor in soup.find_all("a", href=True):
        anchor_text = anchor.get_text(" ", strip=True).lower()
        href = anchor["href"]
        if "rss" in anchor_text or href.lower().endswith((".xml", "/feed", "/feed/", "/rss", "/rss/")):
            full_url = urljoin(base_url, href)
            if urlparse(full_url).netloc == urlparse(base_url).netloc and full_url not in discovered:
                discovered.append(full_url)

    return discovered


def parse_listing_html(html_text: str, source: SourceConfig, limit: int) -> list[RawArticle]:
    """Extract articles from a listing page HTML using source URL patterns."""
    soup = BeautifulSoup(html_text, "html.parser")
    url_regex = re.compile(source.article_url_pattern)
    articles: list[RawArticle] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = anchor["href"]
        full_url = normalize_url(urljoin(source.url, raw_href))
        if not url_regex.match(full_url) or full_url in seen:
            continue

        # Extract the best title candidate inside the anchor or nearby heading
        heading = anchor.find(["h1", "h2", "h3", "h4"])
        title_raw = heading.get_text(" ", strip=True) if heading else anchor.get_text(" ", strip=True)
        title = clean_text(title_raw, max_len=200)
        # Skip non-article navigation labels or very short UI labels
        if len(title) < 12 or title in ("続きを読む", "詳しく見る", "新着記事をもっと見る"):
            continue

        seen.add(full_url)

        # Look at parent container for date, excerpt, and thumbnail
        container = anchor.find_parent(["article", "li", "section", "div"]) or anchor
        container_text = container.get_text(" ", strip=True)
        time_el = container.find("time")
        date_candidate = (
            (time_el.get("datetime") if time_el and time_el.get("datetime") else None)
            or (time_el.get_text(" ", strip=True) if time_el else None)
            or container_text
        )
        published_at = parse_date_to_iso(date_candidate, fallback_url=full_url)

        excerpt = ""
        for p in container.find_all("p"):
            p_text = clean_text(str(p), max_len=260, strip_boilerplate=True)
            if len(p_text) >= 25 and p_text != title:
                excerpt = p_text
                break

        image_url = ""
        img = container.find("img")
        if img:
            src = img.get("data-src") or img.get("src") or ""
            if src and not src.startswith("data:"):
                image_url = urljoin(source.url, src)

        articles.append(
            RawArticle(
                source_id=source.id,
                source_name=source.name,
                title=title,
                url=full_url,
                published_at=published_at,
                excerpt=excerpt,
                tags=[],
                image_url=image_url,
            )
        )
        if len(articles) >= limit:
            break

    return articles


def _enrich_missing_excerpts(
    session: requests.Session,
    articles: list[RawArticle],
    max_fetches: int = 8,
) -> None:
    """Fill missing excerpts/dates from meta description for a bounded number of articles."""
    fetched = 0
    for article in articles:
        if article.excerpt and len(article.excerpt) >= 40:
            continue
        if fetched >= max_fetches:
            break
        try:
            resp = session.get(article.url, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            meta_desc = (
                soup.find("meta", attrs={"property": "og:description"})
                or soup.find("meta", attrs={"name": "description"})
            )
            if meta_desc and meta_desc.get("content"):
                article.excerpt = clean_text(meta_desc["content"], max_len=280, strip_boilerplate=True)
            if not article.image_url:
                og_img = soup.find("meta", attrs={"property": "og:image"})
                if og_img and og_img.get("content"):
                    article.image_url = str(og_img["content"])
            fetched += 1
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Excerpt enrichment failed for %s: %s", article.url, exc)


def fetch_source_articles(
    source: SourceConfig,
    limit: int = DEFAULT_FETCH_LIMIT_PER_SOURCE,
    session: requests.Session | None = None,
) -> tuple[list[RawArticle], str]:
    """Fetch articles from a single source using RSS -> WP API -> HTML fallback.

    Returns (articles, method_used).
    """
    sess = session or _create_session()
    feed_candidates = list(source.feed_urls)

    # 1. Try known RSS/Atom feeds
    for feed_url in feed_candidates:
        try:
            resp = sess.get(feed_url, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200 and resp.content:
                articles = parse_rss_content(resp.content, source, limit)
                if articles:
                    logger.info("[%s] Fetched %d articles via RSS (%s)", source.name, len(articles), feed_url)
                    return articles, f"rss:{feed_url}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] RSS attempt failed (%s): %s", source.name, feed_url, exc)

    # 2. Try WordPress REST API if configured
    if source.wp_api_url:
        try:
            resp = sess.get(source.wp_api_url, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    articles = parse_wp_api_posts(data, source, limit)
                    if articles:
                        logger.info("[%s] Fetched %d articles via WP API", source.name, len(articles))
                        return articles, "wp-json"
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] WP API attempt failed: %s", source.name, exc)

    # 3. Fetch listing HTML -> try auto-discovered RSS first, then parse HTML directly
    for listing_url in source.listing_urls:
        try:
            resp = sess.get(listing_url, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code != 200 or not resp.text:
                continue

            discovered = discover_feed_urls(resp.text, listing_url)
            for disc_url in discovered:
                if disc_url in feed_candidates:
                    continue
                try:
                    feed_resp = sess.get(disc_url, timeout=REQUEST_TIMEOUT_SECONDS)
                    if feed_resp.status_code == 200 and feed_resp.content:
                        articles = parse_rss_content(feed_resp.content, source, limit)
                        if articles:
                            logger.info(
                                "[%s] Fetched %d articles via discovered RSS (%s)",
                                source.name,
                                len(articles),
                                disc_url,
                            )
                            return articles, f"rss-discovered:{disc_url}"
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[%s] Discovered RSS failed (%s): %s", source.name, disc_url, exc)

            articles = parse_listing_html(resp.text, source, limit)
            if articles:
                _enrich_missing_excerpts(sess, articles)
                logger.info("[%s] Fetched %d articles via HTML (%s)", source.name, len(articles), listing_url)
                return articles, f"html:{listing_url}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] Listing HTML attempt failed (%s): %s", source.name, listing_url, exc)

    raise RuntimeError(f"{source.name} から記事を取得できませんでした")
