/* Travel News Monitor — Frontend Logic */

(() => {
  "use strict";

  const DATA_URL = "./data/articles.json";
  const STORAGE_KEYS = {
    read: "tnm_read_ids_v1",
    saved: "tnm_saved_ids_v1",
    theme: "tnm_theme_v1",
  };

  const TOPIC_META = {
    all: {
      label: "すべて",
      description: "HotelBank・訪日ラボ・トラベルボイスの最新記事一覧",
    },
    okinawa: {
      label: "沖縄関連",
      description: "那覇・本島・恩納村・北谷・ジャングリアなど沖縄県全体の宿泊・観光ニュース",
    },
    miyako_ishigaki: {
      label: "宮古島・石垣島",
      description: "宮古諸島・八重山諸島（宮古島・石垣島・下地島・伊良部・西表など）の動向",
    },
    dx: {
      label: "DX関連",
      description: "AI・レベニューマネジメント・省力化・予約システム・キャッシュレス等の宿泊DX",
    },
    saved: {
      label: "保存済み",
      description: "★マークで手元に保存した記事（このブラウザに記憶されます）",
    },
  };

  const state = {
    articles: [],
    meta: {},
    topic: "all",
    source: "all",
    query: "",
    sort: "newest",
    unreadOnly: false,
    readIds: loadIdSet(STORAGE_KEYS.read),
    savedIds: loadIdSet(STORAGE_KEYS.saved),
  };

  const dom = {
    lastUpdated: document.getElementById("last-updated"),
    sourceStatuses: document.getElementById("source-statuses"),
    seedBanner: document.getElementById("seed-banner"),
    closeSeedBanner: document.getElementById("btn-close-seed-banner"),
    topicTabs: document.getElementById("topic-tabs"),
    sourceFilters: document.getElementById("source-filters"),
    searchInput: document.getElementById("search-input"),
    searchClear: document.getElementById("btn-search-clear"),
    sortSelect: document.getElementById("sort-select"),
    unreadToggle: document.getElementById("toggle-unread-only"),
    resultsSummary: document.getElementById("results-summary"),
    topicDescription: document.getElementById("topic-description"),
    articlesGrid: document.getElementById("articles-grid"),
    markAllReadBtn: document.getElementById("btn-mark-all-read"),
    themeToggleBtn: document.getElementById("btn-theme-toggle"),
    themeLabel: document.getElementById("theme-label"),
  };

  function loadIdSet(key) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return new Set();
      const parsed = JSON.parse(raw);
      return new Set(Array.isArray(parsed) ? parsed : []);
    } catch {
      return new Set();
    }
  }

  function saveIdSet(key, idSet) {
    try {
      localStorage.setItem(key, JSON.stringify(Array.from(idSet)));
    } catch {
      // Ignore storage quota errors
    }
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDateDisplay(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;

    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");

    const now = new Date();
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startTarget = new Date(y, date.getMonth(), date.getDate());
    const diffDays = Math.round((startToday - startTarget) / 86400000);

    let rel = "";
    if (diffDays === 0) rel = " · 今日";
    else if (diffDays === 1) rel = " · 昨日";
    else if (diffDays > 1 && diffDays <= 7) rel = ` · ${diffDays}日前`;

    return `${y}.${m}.${d}${rel}`;
  }

  function formatUpdatedAt(isoString) {
    if (!isoString) return "未取得";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    return date.toLocaleString("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function topicPriorityRank(article) {
    const topics = article.topics || [];
    if (topics.includes("miyako_ishigaki")) return 0;
    if (topics.includes("okinawa")) return 1;
    if (topics.includes("dx")) return 2;
    return 3;
  }

  function getFilteredArticles() {
    const q = state.query.trim().toLowerCase();

    const filtered = state.articles.filter((article) => {
      if (state.topic === "saved") {
        if (!state.savedIds.has(article.id)) return false;
      } else if (state.topic !== "all") {
        if (!(article.topics || []).includes(state.topic)) return false;
      }

      if (state.source !== "all" && article.source_id !== state.source) {
        return false;
      }

      if (state.unreadOnly && state.readIds.has(article.id)) {
        return false;
      }

      if (q) {
        const haystack = [
          article.title,
          article.summary,
          article.excerpt,
          article.source_name,
          ...(article.tags || []),
          ...(article.matched_keywords || []),
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }

      return true;
    });

    filtered.sort((a, b) => {
      if (state.sort === "priority") {
        const rankDiff = topicPriorityRank(a) - topicPriorityRank(b);
        if (rankDiff !== 0) return rankDiff;
      }
      return String(b.published_at || "").localeCompare(String(a.published_at || ""));
    });

    return filtered;
  }

  function updateTopicCounts() {
    const sourceScoped =
      state.source === "all"
        ? state.articles
        : state.articles.filter((a) => a.source_id === state.source);

    const counts = {
      all: sourceScoped.length,
      okinawa: sourceScoped.filter((a) => (a.topics || []).includes("okinawa")).length,
      miyako_ishigaki: sourceScoped.filter((a) => (a.topics || []).includes("miyako_ishigaki"))
        .length,
      dx: sourceScoped.filter((a) => (a.topics || []).includes("dx")).length,
      saved: sourceScoped.filter((a) => state.savedIds.has(a.id)).length,
    };

    Object.entries(counts).forEach(([key, value]) => {
      const el = document.getElementById(`count-${key}`);
      if (el) el.textContent = String(value);
    });
  }

  function renderSourceStatuses() {
    const sources = state.meta.sources || [];
    if (!sources.length) {
      dom.sourceStatuses.innerHTML = "";
      return;
    }

    dom.sourceStatuses.innerHTML = sources
      .map((src) => {
        const isErr = src.status !== "ok";
        const countText = isErr ? "取得エラー" : `${src.fetched_count ?? 0}件`;
        return `
          <a class="source-status-item" href="${escapeHtml(src.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(src.error || src.method || "")}">
            <span class="status-dot ${isErr ? "error" : ""}"></span>
            <span>${escapeHtml(src.name)}</span>
            <span class="source-count">${escapeHtml(countText)}</span>
          </a>
        `;
      })
      .join("");
  }

  function renderSummaryHtml(article) {
    const text = String(article.summary || article.excerpt || "").trim();
    if (!text) return "";

    const lines = text
      .split(/\r?\n/)
      .map((line) => line.replace(/^[・•\-*]\s*/, "").trim())
      .filter(Boolean);

    if (lines.length > 1) {
      return `<ul class="card-summary-list">${lines
        .map((line) => `<li>${escapeHtml(line)}</li>`)
        .join("")}</ul>`;
    }
    return `<p style="margin:0;">${escapeHtml(lines[0])}</p>`;
  }

  function renderTopicTags(article) {
    const topics = article.topics || [];
    if (!topics.length) {
      return `<span class="topic-tag general">一般・全国</span>`;
    }
    return topics
      .map((tid) => {
        const label = TOPIC_META[tid]?.label || tid;
        return `<button type="button" class="topic-tag ${escapeHtml(tid)}" data-jump-topic="${escapeHtml(tid)}">${escapeHtml(label)}</button>`;
      })
      .join("");
  }

  function renderArticles() {
    updateTopicCounts();

    const filtered = getFilteredArticles();
    const topicInfo = TOPIC_META[state.topic] || TOPIC_META.all;
    const unreadCount = filtered.filter((a) => !state.readIds.has(a.id)).length;

    dom.resultsSummary.innerHTML = `表示中 <strong>${filtered.length}</strong> 件（未読 <strong>${unreadCount}</strong> 件）`;
    dom.topicDescription.textContent = topicInfo.description;

    if (!filtered.length) {
      dom.articlesGrid.innerHTML = `
        <div class="state-panel">
          <h2>該当する記事がありません</h2>
          <p>フィルター条件や検索キーワードを変更してみてください。</p>
          <button type="button" class="btn-reset" id="btn-reset-filters">フィルターをリセット</button>
        </div>
      `;
      const resetBtn = document.getElementById("btn-reset-filters");
      if (resetBtn) {
        resetBtn.addEventListener("click", resetFilters);
      }
      return;
    }

    dom.articlesGrid.innerHTML = filtered
      .map((article) => {
        const isRead = state.readIds.has(article.id);
        const isSaved = state.savedIds.has(article.id);
        const aiBadge =
          article.summary_type === "ai" ? `<span class="ai-badge">AI要約</span>` : "";

        return `
          <article class="article-card ${isRead ? "is-read" : ""}" data-id="${escapeHtml(article.id)}">
            <div class="card-meta">
              <div class="card-meta-left">
                <span class="source-badge" data-source="${escapeHtml(article.source_id)}">${escapeHtml(article.source_name)}</span>
                <time class="card-date" datetime="${escapeHtml(article.published_at)}">${escapeHtml(formatDateDisplay(article.published_at))}</time>
              </div>
              ${aiBadge}
            </div>

            <h2 class="card-title">
              <a href="${escapeHtml(article.url)}" target="_blank" rel="noopener noreferrer" data-open-article="${escapeHtml(article.id)}">
                ${escapeHtml(article.title)}
              </a>
            </h2>

            <div class="card-summary">
              ${renderSummaryHtml(article)}
            </div>

            <div class="card-footer">
              <div class="card-topics">
                ${renderTopicTags(article)}
              </div>
              <div class="card-actions">
                <button
                  type="button"
                  class="card-action-btn ${isSaved ? "is-saved" : ""}"
                  data-toggle-save="${escapeHtml(article.id)}"
                  aria-pressed="${isSaved}"
                  title="${isSaved ? "保存を解除" : "後で読むに保存"}"
                >
                  <svg viewBox="0 0 24 24" fill="${isSaved ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2">
                    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
                  </svg>
                  <span>${isSaved ? "保存済" : "保存"}</span>
                </button>
                <button
                  type="button"
                  class="card-action-btn"
                  data-toggle-read="${escapeHtml(article.id)}"
                  title="${isRead ? "未読に戻す" : "既読にする"}"
                >
                  <span>${isRead ? "未読へ" : "既読"}</span>
                </button>
                <a
                  class="card-external-link"
                  href="${escapeHtml(article.url)}"
                  target="_blank"
                  rel="noopener noreferrer"
                  data-open-article="${escapeHtml(article.id)}"
                >
                  <span>記事へ</span>
                  <span aria-hidden="true">↗</span>
                </a>
              </div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function setTopic(topicId) {
    state.topic = topicId;
    dom.topicTabs.querySelectorAll(".topic-tab").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.topic === topicId));
    });
    renderArticles();
  }

  function setSource(sourceId) {
    state.source = sourceId;
    dom.sourceFilters.querySelectorAll(".source-chip").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.source === sourceId));
    });
    renderArticles();
  }

  function resetFilters() {
    state.topic = "all";
    state.source = "all";
    state.query = "";
    state.unreadOnly = false;
    dom.searchInput.value = "";
    dom.searchClear.hidden = true;
    dom.unreadToggle.checked = false;
    setTopic("all");
    setSource("all");
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    dom.themeLabel.textContent = theme === "dark" ? "ライト" : "ダーク";
    try {
      localStorage.setItem(STORAGE_KEYS.theme, theme);
    } catch {
      // Ignore storage error
    }
  }

  function initTheme() {
    let saved = null;
    try {
      saved = localStorage.getItem(STORAGE_KEYS.theme);
    } catch {
      saved = null;
    }
    const prefersDark =
      window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(saved || (prefersDark ? "dark" : "light"));
  }

  function bindEvents() {
    dom.topicTabs.addEventListener("click", (event) => {
      const btn = event.target.closest(".topic-tab");
      if (!btn || !btn.dataset.topic) return;
      setTopic(btn.dataset.topic);
    });

    dom.sourceFilters.addEventListener("click", (event) => {
      const btn = event.target.closest(".source-chip");
      if (!btn || !btn.dataset.source) return;
      setSource(btn.dataset.source);
    });

    dom.searchInput.addEventListener("input", () => {
      state.query = dom.searchInput.value;
      dom.searchClear.hidden = !state.query;
      renderArticles();
    });

    dom.searchClear.addEventListener("click", () => {
      state.query = "";
      dom.searchInput.value = "";
      dom.searchClear.hidden = true;
      dom.searchInput.focus();
      renderArticles();
    });

    dom.sortSelect.addEventListener("change", () => {
      state.sort = dom.sortSelect.value;
      renderArticles();
    });

    dom.unreadToggle.addEventListener("change", () => {
      state.unreadOnly = dom.unreadToggle.checked;
      renderArticles();
    });

    dom.markAllReadBtn.addEventListener("click", () => {
      const visible = getFilteredArticles();
      visible.forEach((article) => state.readIds.add(article.id));
      saveIdSet(STORAGE_KEYS.read, state.readIds);
      renderArticles();
    });

    dom.themeToggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      applyTheme(current === "dark" ? "light" : "dark");
    });

    dom.closeSeedBanner.addEventListener("click", () => {
      dom.seedBanner.hidden = true;
    });

    dom.articlesGrid.addEventListener("click", (event) => {
      const jumpBtn = event.target.closest("[data-jump-topic]");
      if (jumpBtn) {
        setTopic(jumpBtn.dataset.jumpTopic);
        return;
      }

      const saveBtn = event.target.closest("[data-toggle-save]");
      if (saveBtn) {
        const id = saveBtn.dataset.toggleSave;
        if (state.savedIds.has(id)) state.savedIds.delete(id);
        else state.savedIds.add(id);
        saveIdSet(STORAGE_KEYS.saved, state.savedIds);
        renderArticles();
        return;
      }

      const readBtn = event.target.closest("[data-toggle-read]");
      if (readBtn) {
        const id = readBtn.dataset.toggleRead;
        if (state.readIds.has(id)) state.readIds.delete(id);
        else state.readIds.add(id);
        saveIdSet(STORAGE_KEYS.read, state.readIds);
        renderArticles();
        return;
      }

      const openLink = event.target.closest("[data-open-article]");
      if (openLink) {
        const id = openLink.dataset.openArticle;
        if (!state.readIds.has(id)) {
          state.readIds.add(id);
          saveIdSet(STORAGE_KEYS.read, state.readIds);
          renderArticles();
        }
      }
    });

    // Keyboard shortcuts for rapid morning briefing navigation
    document.addEventListener("keydown", (event) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (event.key === "Escape") {
          document.activeElement.blur();
        }
        return;
      }

      if (event.key === "/") {
        event.preventDefault();
        dom.searchInput.focus();
      } else if (event.key === "1") {
        setTopic("all");
      } else if (event.key === "2") {
        setTopic("okinawa");
      } else if (event.key === "3") {
        setTopic("miyako_ishigaki");
      } else if (event.key === "4") {
        setTopic("dx");
      }
    });
  }

  async function loadData() {
    try {
      const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      state.meta = data.meta || {};
      state.articles = Array.isArray(data.articles) ? data.articles : [];

      dom.lastUpdated.textContent = formatUpdatedAt(state.meta.updated_at);
      renderSourceStatuses();

      const hasOnlySeed =
        Boolean(state.meta.is_initial_seed) ||
        (state.articles.length > 0 && state.articles.every((a) => a.is_seed));
      dom.seedBanner.hidden = !hasOnlySeed;

      renderArticles();
    } catch (err) {
      dom.lastUpdated.textContent = "取得失敗";
      dom.articlesGrid.innerHTML = `
        <div class="state-panel">
          <h2>記事データの読み込みに失敗しました</h2>
          <p>${escapeHtml(err.message)} — ローカル確認時は <code>python3 -m http.server -d docs</code> などで開いてください。</p>
        </div>
      `;
    }
  }

  initTheme();
  bindEvents();
  loadData();
})();
