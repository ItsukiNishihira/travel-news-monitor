"""Unit tests for the travel news monitor collection pipeline."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.classifier import classify_article
from scripts.config import SOURCES
from scripts.fetchers import (
    RawArticle,
    clean_text,
    discover_feed_urls,
    normalize_url,
    parse_listing_html,
    parse_rss_content,
    parse_wp_api_posts,
)
from scripts.slack_notify import build_slack_payload
from scripts.summarizer import summarize_article
from scripts.collect import run_collection


class TestClassifier(unittest.TestCase):
    def test_miyako_ishigaki_also_tags_okinawa(self) -> None:
        topics, keywords = classify_article(
            title="宮古島のホテル供給は9年で2.9倍、投資に必要なADRは6.4万円",
            summary="下地島空港の国際線利用増が追い風。",
        )
        self.assertIn("miyako_ishigaki", topics)
        self.assertIn("okinawa", topics)
        self.assertTrue(len(keywords) > 0)

    def test_iwate_miyako_excluded(self) -> None:
        topics, _ = classify_article(
            title="岩手県宮古市の観光振興計画について",
            summary="三陸エリアの宿泊需要を分析。",
        )
        self.assertNotIn("miyako_ishigaki", topics)
        self.assertNotIn("okinawa", topics)

    def test_dx_word_boundary_prevents_false_positives(self) -> None:
        topics, _ = classify_article(
            title="京都の老舗旅館、秋の懐石料理プランを発売",
            summary="Emailでのお問い合わせにも対応しています。",
        )
        self.assertNotIn("dx", topics)

        dx_topics, _ = classify_article(
            title="宿泊業の省力化投資補助金とAIレベニューマネジメント導入事例",
            summary="PMSとスマートチェックイン連携で業務効率化。",
        )
        self.assertIn("dx", dx_topics)

    def test_combined_okinawa_and_dx(self) -> None:
        topics, _ = classify_article(
            title="那覇のホテルで無人チェックインとダイナミックプライシングを導入",
            summary="沖縄県内の人手不足対策としてDXを推進。",
        )
        self.assertEqual(topics, ["okinawa", "dx"])


class TestFetchersParsing(unittest.TestCase):
    def test_normalize_url(self) -> None:
        self.assertEqual(
            normalize_url("https://HotelBank.jp/investment/sample-post/?utm_source=x#top"),
            "https://hotelbank.jp/investment/sample-post",
        )

    def test_clean_text_japanese_spacing_and_boilerplate(self) -> None:
        raw_html = (
            '<p><a href="#">大阪</a> <a href="#">観光局</a> は、'
            '<a href="#">関西</a> 空港から出国する <a href="#">訪日外国人</a> を対象とした'
            '「 <a href="#">World Travel Awards</a> 」と（ JNTO ）調査を発表しました。'
            "[RegistrationWall] 関連記事：別の記事タイトル 目次 見出し1</p>"
        )
        cleaned = clean_text(raw_html, strip_boilerplate=True)
        self.assertEqual(
            cleaned,
            "大阪観光局は、関西空港から出国する訪日外国人を対象とした「World Travel Awards」と（JNTO）調査を発表しました。",
        )

    def test_clean_text_strips_truncated_shortcode(self) -> None:
        raw = "ZIPAIR Tokyo（以下、 ZIPAIR ）は11月12日に就航を発表しました。 [Regist"
        cleaned = clean_text(raw, strip_boilerplate=True)
        self.assertEqual(
            cleaned,
            "ZIPAIR Tokyo（以下、ZIPAIR）は11月12日に就航を発表しました。",
        )

    def test_parse_rss_content(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Travel Voice</title>
          <item>
            <title>【図解】訪日外国人数、2026年10月は391万人で過去最多</title>
            <link>https://www.travelvoice.jp/20261118-160001</link>
            <pubDate>Wed, 18 Nov 2026 09:00:00 +0900</pubDate>
            <description><![CDATA[<p>日本政府観光局（JNTO）が速報を発表。</p>]]></description>
          </item>
        </channel></rss>
        """
        tv_source = next(s for s in SOURCES if s.id == "travelvoice")
        articles = parse_rss_content(xml, tv_source, limit=10)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].source_id, "travelvoice")
        self.assertIn("391万人", articles[0].title)
        self.assertTrue(articles[0].published_at.startswith("2026-11-18"))

    def test_parse_wp_api_posts(self) -> None:
        hb_source = next(s for s in SOURCES if s.id == "hotelbank")
        posts = [
            {
                "link": "https://hotelbank.jp/investment/okinawa-hotel-openings-2026/",
                "date": "2026-11-12T10:00:00",
                "title": {"rendered": "沖縄のホテル新規開業2026は104軒2950室"},
                "excerpt": {"rendered": "<p>那覇・北谷・宮古島・恩納のADRを分析。</p>"},
                "_embedded": {
                    "wp:term": [[{"name": "投資・開発"}, {"name": "新規開業・供給"}]],
                },
            }
        ]
        articles = parse_wp_api_posts(posts, hb_source, limit=10)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].tags, ["投資・開発", "新規開業・供給"])

    def test_parse_honichi_listing_html_and_discover_feed(self) -> None:
        html_doc = """
        <html>
          <head>
            <link rel="alternate" type="application/rss+xml" href="/news/rss.xml" />
          </head>
          <body>
            <article>
              <a href="/news/2026/11/20/netstars-refund/">
                <h3>ネットスターズ、リファンド方式対応の免税送金サービス開始</h3>
              </a>
              <time>2026年11月20日</time>
              <p>新たな消費税免税制度リファンド方式に対応する送金サービスを開始しました。</p>
            </article>
          </body>
        </html>
        """
        honichi = next(s for s in SOURCES if s.id == "honichi")
        feeds = discover_feed_urls(html_doc, "https://honichi.com/news/")
        self.assertEqual(feeds, ["https://honichi.com/news/rss.xml"])

        articles = parse_listing_html(html_doc, honichi, limit=10)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].url, "https://honichi.com/news/2026/11/20/netstars-refund")
        self.assertTrue(articles[0].published_at.startswith("2026-11-20"))


class TestSummarizerAndSlackAndPipeline(unittest.TestCase):
    def test_summarizer_falls_back_to_excerpt_without_api_keys(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            summary, summary_type = summarize_article(
                title="テスト記事",
                excerpt="沖縄県内の宿泊施設向け省力化投資補助金の詳細解説。",
                source_name="HotelBank",
            )
            self.assertEqual(summary_type, "excerpt")
            self.assertIn("省力化投資補助金", summary)

    def test_slack_payload_prioritizes_topics(self) -> None:
        articles = [
            {
                "title": "一般ニュース",
                "url": "https://example.com/1",
                "source_name": "トラベルボイス",
                "published_at": "2026-11-20T12:00:00+09:00",
                "summary": "一般記事の抜粋",
                "summary_type": "excerpt",
                "topics": [],
            },
            {
                "title": "石垣島の新規リゾート開業",
                "url": "https://example.com/2",
                "source_name": "HotelBank",
                "published_at": "2026-11-20T09:00:00+09:00",
                "summary": "石垣島の供給動向",
                "summary_type": "ai",
                "topics": ["miyako_ishigaki", "okinawa"],
            },
        ]
        payload = build_slack_payload(articles, site_url="https://example.github.io/travel-news-monitor/")
        section_blocks = [b for b in payload["blocks"] if b["type"] == "section"]
        self.assertEqual(len(section_blocks), 2)
        # Miyako/Ishigaki article must appear first
        self.assertIn("石垣島の新規リゾート開業", section_blocks[0]["text"]["text"])
        self.assertIn("✨AI要約", section_blocks[0]["text"]["text"])

    def test_end_to_end_pipeline_deduplication(self) -> None:
        mock_articles = [
            RawArticle(
                source_id="hotelbank",
                source_name="HotelBank",
                title="Minn 那覇美栄橋が開業、全42室のアパートメントホテル",
                url="https://hotelbank.jp/supply-pipeline/minn-naha-miebashi/",
                published_at="2026-11-18T10:00:00+09:00",
                excerpt="沖縄県初となるMinn那覇美栄橋が開業。",
            ),
            RawArticle(
                source_id="honichi",
                source_name="訪日ラボ",
                title="AIが選ぶホテルTOP10と免税リファンド方式の最新動向",
                url="https://honichi.com/news/2026/11/20/ai-hotel-refund/",
                published_at="2026-11-20T09:00:00+09:00",
                excerpt="AI活用と免税DXに関する最新レポート。",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "articles.json"

            def fake_fetch(source, limit=25, session=None):
                matched = [a for a in mock_articles if a.source_id == source.id]
                return matched, "mock"

            with patch("scripts.collect.fetch_source_articles", side_effect=fake_fetch):
                with patch.dict("os.environ", {}, clear=True):
                    first = run_collection(data_path=data_path, skip_notify=True)
                    self.assertEqual(first["meta"]["total_articles"], 2)
                    self.assertEqual(first["meta"]["new_articles_last_run"], 2)
                    self.assertEqual(first["meta"]["topic_counts"]["okinawa"], 1)
                    self.assertEqual(first["meta"]["topic_counts"]["dx"], 1)

                    # Second run with identical articles should produce 0 new articles
                    second = run_collection(data_path=data_path, skip_notify=True)
                    self.assertEqual(second["meta"]["total_articles"], 2)
                    self.assertEqual(second["meta"]["new_articles_last_run"], 0)

                    saved = json.loads(data_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(saved["articles"]), 2)


if __name__ == "__main__":
    unittest.main()
