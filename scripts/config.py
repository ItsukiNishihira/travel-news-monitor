"""Configuration for news sources and topic classification rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = REPO_ROOT / "docs" / "data" / "articles.json"

MAX_STORED_ARTICLES = 300
DEFAULT_FETCH_LIMIT_PER_SOURCE = 25
REQUEST_TIMEOUT_SECONDS = 20

USER_AGENT = (
    "TravelNewsMonitor/1.0 (+https://github.com/ItsukiNishihira/travel-news-monitor)"
)


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    url: str
    feed_urls: tuple[str, ...]
    wp_api_url: str | None
    listing_urls: tuple[str, ...]
    article_url_pattern: str


SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        id="hotelbank",
        name="HotelBank",
        url="https://hotelbank.jp/",
        feed_urls=(
            "https://hotelbank.jp/feed/",
            "https://hotelbank.jp/rss.xml",
        ),
        wp_api_url="https://hotelbank.jp/wp-json/wp/v2/posts?per_page=25&_embed=1",
        listing_urls=(
            "https://hotelbank.jp/",
        ),
        article_url_pattern=r"^https://hotelbank\.jp/(?!category/|tag/|author/|page/|wp-|about|contact|privacy|terms|newsletter)[a-z0-9-]+/[a-z0-9%-]+/?$",
    ),
    SourceConfig(
        id="honichi",
        name="訪日ラボ",
        url="https://honichi.com/",
        feed_urls=(
            "https://honichi.com/news/rss",
            "https://honichi.com/news/feed",
            "https://honichi.com/rss",
            "https://honichi.com/feed",
        ),
        wp_api_url=None,
        listing_urls=(
            "https://honichi.com/news/",
            "https://honichi.com/",
        ),
        article_url_pattern=r"^https://honichi\.com/news/\d{4}/\d{2}/\d{2}/[^/?#]+/?$",
    ),
    SourceConfig(
        id="travelvoice",
        name="トラベルボイス",
        url="https://www.travelvoice.jp/",
        feed_urls=(
            "https://www.travelvoice.jp/feed",
            "https://www.travelvoice.jp/rss.xml",
        ),
        wp_api_url="https://www.travelvoice.jp/wp-json/wp/v2/posts?per_page=25&_embed=1",
        listing_urls=(
            "https://www.travelvoice.jp/news",
            "https://www.travelvoice.jp/",
        ),
        article_url_pattern=r"^https://www\.travelvoice\.jp/\d{8}-\d+/?$",
    ),
)


@dataclass(frozen=True)
class TopicDefinition:
    id: str
    label: str
    short_label: str
    description: str
    substring_keywords: tuple[str, ...]
    word_keywords: tuple[str, ...] = ()
    exclude_if_contains: tuple[str, ...] = ()


TOPICS: tuple[TopicDefinition, ...] = (
    TopicDefinition(
        id="miyako_ishigaki",
        label="宮古島・石垣島",
        short_label="宮古・石垣",
        description="宮古諸島・八重山諸島（宮古島・石垣島・下地島・伊良部・竹富・西表など）の宿泊・観光動向",
        substring_keywords=(
            "宮古島",
            "宮古空港",
            "宮古圏",
            "宮古市",
            "下地島",
            "伊良部島",
            "伊良部大橋",
            "伊良部",
            "来間島",
            "池間島",
            "シギラ",
            "平良",
            "トゥリバー",
            "石垣島",
            "石垣市",
            "石垣空港",
            "南ぬ島",
            "八重山",
            "竹富島",
            "竹富町",
            "西表島",
            "小浜島",
            "黒島",
            "波照間",
            "与那国",
            "先島",
            "miyakojima",
            "ishigaki",
            "yaeyama",
            "shimojishima",
            "shigira",
        ),
        word_keywords=(
            "miyako",
        ),
        exclude_if_contains=(
            "岩手県宮古市",
        ),
    ),
    TopicDefinition(
        id="okinawa",
        label="沖縄関連",
        short_label="沖縄",
        description="沖縄本島・那覇・恩納村・北谷・ジャングリアなど沖縄県全体の宿泊・観光ニュース",
        substring_keywords=(
            "沖縄",
            "那覇",
            "美栄橋",
            "国際通り",
            "恩納村",
            "恩納",
            "北谷",
            "名護",
            "浦添",
            "糸満",
            "豊見城",
            "読谷",
            "宜野湾",
            "うるま",
            "本部町",
            "やんばる",
            "ジャングリア",
            "首里",
            "琉球",
            "美ら海",
            "瀬長島",
            "久米島",
            "慶良間",
            "座間味",
            "渡嘉敷",
            "古宇利",
            "万座",
            "残波",
            "宜野座",
            "今帰仁",
            "おきなわ",
            "okinawa",
            "naha",
            "junglia",
            "ryukyu",
        ),
        word_keywords=(
            "ocvb",
        ),
    ),
    TopicDefinition(
        id="dx",
        label="DX関連",
        short_label="DX",
        description="AI・レベニューマネジメント・省力化・PMS/OTA・キャッシュレス・データ活用など宿泊DX",
        substring_keywords=(
            "生成ai",
            "chatgpt",
            "claude",
            "gemini",
            "レベニューマネジメント",
            "レベニュー",
            "ダイナミックプライシング",
            "サイトコントローラー",
            "ブッキングエンジン",
            "ブッキングカーブ",
            "省力化",
            "無人ホテル",
            "無人運営",
            "非対面",
            "非接触",
            "スマートロック",
            "スマートチェックイン",
            "自動チェックイン",
            "セルフチェックイン",
            "モバイルオーダー",
            "自動化",
            "ロボット",
            "配膳ロボ",
            "清掃ロボ",
            "クラウド",
            "予約システム",
            "システム導入",
            "データ活用",
            "データ分析",
            "ビッグデータ",
            "デジタル化",
            "デジタル",
            "キャッシュレス",
            "電子決済",
            "免税送金",
            "リファンド方式",
            "顔認証",
            "生体認証",
            "チャットボット",
            "口コミ分析",
            "クチコミ分析",
            "口コミ管理",
            "googleマップ",
            "googleビジネスプロフィール",
            "アプリ",
            "テクノロジー",
            "it導入",
            "業務効率化",
            "自動化ツール",
            "revenue-management",
            "dynamic-pricing",
            "hoteltech",
            "メトロエンジン",
            "口コミコム",
        ),
        word_keywords=(
            "dx",
            "ai",
            "llm",
            "rms",
            "pms",
            "ota",
            "iot",
            "saas",
            "crm",
            "maas",
            "daas",
            "mcp",
            "meo",
            "api",
            "rpa",
            "ict",
            "nfc",
            "qr",
        ),
    ),
)

TOPIC_MAP: dict[str, TopicDefinition] = {topic.id: topic for topic in TOPICS}
