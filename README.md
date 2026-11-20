# travel-news-monitor — 沖縄宿泊ニュース・ブリーフ

沖縄県宿泊業・観光業向けに、主要3メディアの最新記事を **GitHub Actions で毎日自動収集・重複排除・分野分類・（任意でAI要約）・Slack通知** し、**GitHub Pages** 上の個人用ニュースサイトで一覧閲覧できる完全無料のシステムです。

## 収集対象メディア（3サイト）

1. **HotelBank** (`https://hotelbank.jp/`)
2. **訪日ラボ** (`https://honichi.com/`)
3. **トラベルボイス** (`https://www.travelvoice.jp/`)

各サイトとも **RSS / WordPress REST API / HTML一覧ページ** の多段フォールバックで収集するため、フィード仕様が変わっても安定稼働します。

## 主な機能

- **3分野の自動分類＆ワンクリックフィルター**
  - **沖縄関連**（那覇・本島・恩納村・北谷・ジャングリア・沖縄観光など）
  - **宮古島・石垣島**（宮古島・下地島・伊良部・石垣島・八重山・西表・竹富など）
  - **DX関連**（AI・レベニューマネジメント・省力化・予約システム・PMS/OTA・キャッシュレス・免税リファンド等）
- **ハイブリッドAI要約**
  - GitHub Secrets に `GEMINI_API_KEY` または `OPENAI_API_KEY`（または `LLM_API_KEY`）を登録すると、新着記事を日本語3行で自動要約します。
  - 未設定の場合は記事の冒頭抜粋を自動表示するため、API費用ゼロでもそのまま動作します。
- **Slack通知（Incoming Webhook）**
  - 毎朝（日本時間 08:00）の新着記事を、宮古島・石垣島 → 沖縄関連 → DX関連 → その他の優先順で Slack に通知します。
- **個人用Webサイト（GitHub Pages）**
  - 分野別タブ、3サイト別フィルター、リアルタイム検索、未読のみ表示、★お気に入り保存、既読管理、ライト/ダークモード、キーボードショートカット（`/` で検索、`1`〜`4` で分野切替）に対応。

---

## セットアップ手順（初回のみ・5分で完了）

### 1. GitHub Pages を有効にする
1. リポジトリの **Settings → Pages** を開きます。
2. **Build and deployment → Source** で **Deploy from a branch** を選択します。
3. **Branch** に `main`、フォルダに **`/docs`** を選んで **Save** をクリックします。
4. 数分後に `https://itsukinishihira.github.io/travel-news-monitor/` で個人用サイトが開けるようになります。

### 2. Slack通知を設定する（任意）
1. Slack で Incoming Webhook を作成し、Webhook URL を取得します。
2. リポジトリの **Settings → Secrets and variables → Actions → Secrets** で以下を追加します：
   - Name: `SLACK_WEBHOOK_URL`
   - Secret: 取得した Webhook URL
3. 沖縄・宮古石垣・DXの3分野に該当する記事だけをSlack通知したい場合は、**Variables** タブに `SLACK_NOTIFY_FILTER` = `topics` を追加します（未設定時は全件通知）。

### 3. AI 3行要約を有効にする（任意）
**Settings → Secrets and variables → Actions → Secrets** にいずれか1つを登録するだけで自動有効化されます：
- `GEMINI_API_KEY`（Google AI Studio の APIキー / デフォルトモデル: `gemini-2.5-flash`）
- `OPENAI_API_KEY`（OpenAI の APIキー / デフォルトモデル: `gpt-4o-mini`）
- `LLM_API_KEY`（汎用。`AIza...` なら Gemini、それ以外は OpenAI として自動判別）

### 4. 初回の手動実行で確認する
1. リポジトリの **Actions** タブ → **Collect Travel & Hotel News** を開きます。
2. **Run workflow** をクリックして実行します。
3. 完了すると `docs/data/articles.json` が最新の記事データで自動更新され、Slack にも通知が届きます。

---

## ローカル開発・テスト

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ユニットテストの実行
python -m unittest discover -s tests -v

# 収集スクリプトの手動実行（Slack通知スキップ）
python scripts/collect.py --skip-notify

# 個人用サイトのローカルプレビュー
python3 -m http.server 8000 -d docs
```

## ディレクトリ構成

```text
.
├── .github/workflows/collect.yml  # 毎日08:00 JST自動収集・通知・JSONコミット
├── scripts/
│   ├── config.py                  # 3サイト設定・3分野キーワード定義
│   ├── fetchers.py                # RSS / WP REST API / HTML 多段フェッチャー
│   ├── classifier.py              # 沖縄・宮古島石垣島・DX 自動分類
│   ├── summarizer.py              # ハイブリッドAI要約（未設定時は抜粋）
│   ├── slack_notify.py            # Slack Block Kit 通知
│   └── collect.py                 # メイン収集パイプライン
├── tests/
│   └── test_pipeline.py           # ユニットテスト
└── docs/                          # GitHub Pages 公開ディレクトリ
    ├── index.html
    ├── styles.css
    ├── app.js
    └── data/articles.json
```
