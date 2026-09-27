import { announceAccountChange, watchAccountSession } from "./account_session.js";

/*
 * Arena composition root.
 *
 * The arena is a small, state-driven flow that deliberately lives outside
 * the match GUI. The server owns the run and its revision; this module only
 * renders the current state and submits one explicit choice at a time.
 */

const COPY = {
  zhCN: {
    back: "返回开始界面",
    title: "竞技场",
    subtitle: "选择卡池，挑选英雄，组建三十张牌组。",
    language: "界面语言",
    wins: "胜",
    losses: "负",
    stepSetup: "选包",
    stepHero: "选英雄",
    stepDraft: "选牌",
    stepReady: "开战",
    setupTitle: "选择竞技场卡池",
    setupIntro: "基础和经典卡牌固定在卡池中，不计入 16 点预算。另选扩展包：大包 3 点，小包 1 点。",
    nickname: "竞技场昵称",
    nicknamePlaceholder: "例如：旅店老板",
    nicknameHint: "昵称只保存在这台设备上。",
    basicLocked: "BASIC · 已锁定",
    basicDescription: "基础卡牌始终加入竞技场卡池，不占扩展包预算。",
    classicLocked: "经典 · 已锁定",
    classicDescription: "经典卡牌始终加入竞技场卡池，不占扩展包预算。",
    largePacks: "大包",
    smallPacks: "小包",
    cards: "张卡",
    points: "点",
    selectedPacks: "已选卡包",
    budget: "卡池预算",
    budgetRule: "需要正好 16 点：5 个大包 + 1 个小包，或用 3 个小包替代 1 个大包。",
    budgetReady: "卡池选择完成，可以开始选英雄。",
    budgetInvalid: "还需要选择到正好 16 点的卡池。",
    startArena: "开始竞技场",
    starting: "正在创建竞技场……",
    heroTitle: "选择你的英雄",
    heroIntro: "从三个随机英雄中选择一个。之后的三十轮选牌会遵循这个职业和当前卡池。",
    chooseHero: "选择这个英雄",
    draftTitle: "选择一张卡牌",
    draftIntro: "每轮从三张牌中选择一张加入牌组。白板牌也会出现在首版卡池中。",
    draftProgress: "第 {current} / {total} 轮",
    pickCard: "选择这张牌",
    deckTitle: "你的竞技场牌组",
    deckCount: "{count} / 30 张",
    manaCurve: "法力曲线",
    manaBucket: "{cost} 费：{count} 张",
    chosenHero: "已选英雄",
    className: "职业",
    setName: "系列",
    cost: "费用",
    attack: "攻击",
    health: "生命",
    noText: "暂无卡牌文字。",
    readyTitle: "牌组已经完成",
    readyIntro: "三十张牌已经加入牌组。确认后进入本机对战。",
    enterBattle: "进入对战",
    launching: "正在进入对战……",
    completeTitle: "竞技场结束",
    completeIntro: "本次竞技场已达到 7 胜或 3 负。",
    finalRecord: "最终战绩",
    startAgain: "重新开始",
    loading: "正在读取竞技场状态……",
    waiting: "正在等待服务器……",
    scriptYes: "有 Python 定义",
    scriptNo: "无 Python 定义",
    unknownSet: "未标记系列",
    unknownClass: "中立",
    missingArt: "暂无图片",
    requestFailed: "竞技场请求失败：{message}",
    invalidName: "请输入竞技场昵称。",
    invalidBudget: "请选择正好 16 点的扩展包。",
    network: "无法连接本机竞技场服务。",
    reset: "返回选包",
  },
  enUS: {
    back: "Back to start",
    title: "Arena",
    subtitle: "Choose a pool, pick a hero, and draft a 30-card deck.",
    language: "Language",
    wins: "W",
    losses: "L",
    stepSetup: "Packs",
    stepHero: "Hero",
    stepDraft: "Draft",
    stepReady: "Battle",
    setupTitle: "Choose your arena pool",
    setupIntro: "Basic and Classic cards are always in the pool and cost no points. Choose expansions worth 16 points: large packs cost 3 and small packs cost 1.",
    nickname: "Arena nickname",
    nicknamePlaceholder: "For example: Innkeeper",
    nicknameHint: "Your nickname stays on this device.",
    basicLocked: "BASIC · Locked",
    basicDescription: "Basic cards are always in the arena pool and do not use expansion points.",
    classicLocked: "Classic · Locked",
    classicDescription: "Classic cards are always in the arena pool and do not use expansion points.",
    largePacks: "Large packs",
    smallPacks: "Small packs",
    cards: "cards",
    points: "pts",
    selectedPacks: "Selected packs",
    budget: "Pool budget",
    budgetRule: "Use exactly 16 points: 5 large + 1 small, or replace a large pack with 3 small packs.",
    budgetReady: "Pool complete. You can choose your hero.",
    budgetInvalid: "Choose packs worth exactly 16 points.",
    startArena: "Start arena",
    starting: "Creating arena run…",
    heroTitle: "Choose your hero",
    heroIntro: "Pick one of three random heroes. The next thirty draft rounds follow this class and pool.",
    chooseHero: "Choose this hero",
    draftTitle: "Choose a card",
    draftIntro: "Pick one of three cards to add to your deck. Blank cards are allowed in the first version.",
    draftProgress: "Round {current} / {total}",
    pickCard: "Choose this card",
    deckTitle: "Your arena deck",
    deckCount: "{count} / 30 cards",
    manaCurve: "Mana curve",
    manaBucket: "{cost} mana: {count} cards",
    chosenHero: "Chosen hero",
    className: "Class",
    setName: "Set",
    cost: "Cost",
    attack: "Attack",
    health: "Health",
    noText: "No card text available.",
    readyTitle: "Deck complete",
    readyIntro: "Thirty cards are in your deck. Enter local battle when ready.",
    enterBattle: "Enter battle",
    launching: "Entering battle…",
    completeTitle: "Arena complete",
    completeIntro: "This arena ended at 7 wins or 3 losses.",
    finalRecord: "Final record",
    startAgain: "Start again",
    loading: "Loading arena state…",
    waiting: "Waiting for the server…",
    scriptYes: "Python definition found",
    scriptNo: "No Python definition",
    unknownSet: "Unmarked set",
    unknownClass: "Neutral",
    missingArt: "No image",
    requestFailed: "Arena request failed: {message}",
    invalidName: "Enter an arena nickname.",
    invalidBudget: "Choose exactly 16 expansion points.",
    network: "The local arena service is unavailable.",
    reset: "Back to packs",
  },
};

const refs = {
  stage: document.getElementById("arena-stage"),
  loading: document.getElementById("arena-loading"),
  status: document.getElementById("arena-status"),
  error: document.getElementById("arena-error"),
  headerWins: document.getElementById("arena-header-wins"),
  headerLosses: document.getElementById("arena-header-losses"),
  accountToolbar: document.getElementById("arena-account-toolbar"),
  accountLabel: document.getElementById("arena-account-label"),
  accountImport: document.getElementById("arena-account-import"),
  accountLogout: document.getElementById("arena-account-logout"),
  localeButtons: [...document.querySelectorAll("[data-locale]")],
  copyNodes: [...document.querySelectorAll("[data-copy]")],
  progress: [...document.querySelectorAll(".arena-progress-step")],
};

const model = {
  locale: readLocale(),
  state: null,
  selectedPacks: new Set(),
  busy: false,
  status: "",
  imageUrls: new Set(),
  imageGeneration: 0,
  account: null,
  legacyAvailable: false,
};

function readLocale() {
  try {
    return localStorage.getItem("fireplace.locale") === "enUS" ? "enUS" : "zhCN";
  } catch (_error) {
    return "zhCN";
  }
}

function storeLocale(locale) {
  try {
    localStorage.setItem("fireplace.locale", locale);
  } catch (_error) {
    // The UI remains usable in private browsing mode.
  }
}

function currentPath() {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") ? path : "/arena";
}

function accountUrl() {
  return `/account?next=${encodeURIComponent(currentPath())}`;
}

function nicknameStorageKey() {
  return `fireplace.nickname.${model.account?.id || "anonymous"}`;
}

function accountFromPayload(payload) {
  const account = payload?.account;
  if (!payload?.authenticated || !account || typeof account !== "object") return null;
  const username = text(account.username).trim();
  const id = text(account.id).trim();
  return username && id ? { id, username } : null;
}

function renderAccountControls() {
  const authenticated = Boolean(model.account);
  refs.accountToolbar.hidden = !authenticated;
  refs.accountLabel.textContent = authenticated ? model.account.username : "";
  refs.accountLabel.href = "/account";
  refs.accountLabel.setAttribute("aria-label", authenticated ? `打开账号页面: ${model.account.username}` : "");
  refs.accountLogout.textContent = model.locale === "enUS" ? "Log out" : "退出登录";
  refs.accountImport.textContent = model.locale === "enUS" ? "Import old data" : "导入旧数据";
  refs.accountImport.hidden = !authenticated || !model.legacyAvailable;
  refs.accountImport.title = model.locale === "enUS"
    ? "Import local decks and Arena progress from before accounts were added."
    : "导入账号创建前的本机卡组和竞技场进度。";
  refs.accountLogout.disabled = model.busy;
  refs.accountImport.disabled = model.busy;
}

async function loadAccountSession() {
  try {
    const payload = await request("/api/account/session");
    model.account = accountFromPayload(payload);
    model.legacyAvailable = payload?.legacy_available === true;
  } catch (_error) {
    model.account = null;
    model.legacyAvailable = false;
  }
  if (!model.account) {
    window.location.replace(accountUrl());
    return false;
  }
  renderAccountControls();
  return true;
}

async function logoutAccount() {
  if (model.busy) return;
  try {
    await request("/api/account/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    announceAccountChange();
  } catch (_error) {
    // The account page still clears the private view if the server has stopped.
  }
  window.location.replace("/account?next=%2F");
}

async function importLegacy() {
  if (model.busy || !model.legacyAvailable) return;
  if (!model.account) return;
  const message = model.locale === "enUS"
    ? "Import the old local decks and Arena progress into this account? The original files will be kept."
    : "将旧的本机卡组和竞技场进度导入当前账号吗？原始文件会保留。";
  if (!window.confirm(message)) return;
  setBusy(true);
  setError("");
  setStatus(model.locale === "enUS" ? "Importing old data…" : "正在导入旧数据……");
  try {
    await request("/api/account/import-legacy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: model.account.id }),
    });
    model.legacyAvailable = false;
    renderAccountControls();
    setStatus(model.locale === "enUS" ? "Old data was imported into this account." : "旧数据已导入当前账号。");
    const payload = await request(`/api/arena/state?locale=${encodeURIComponent(model.locale)}`);
    applyState(payload);
  } catch (error) {
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    setBusy(false);
    renderAccountControls();
  }
}

function t(key, variables = {}) {
  const value = COPY[model.locale]?.[key] ?? COPY.zhCN[key] ?? key;
  return String(value).replace(/\{(\w+)\}/g, (_match, name) => String(variables[name] ?? ""));
}

function text(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function escapeHtml(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeId(value) {
  return encodeURIComponent(text(value));
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function numberOrDash(value) {
  return value === null || value === undefined || value === "" ? "—" : text(value);
}

function localeName() {
  return model.locale === "enUS" ? "English" : "中文";
}

function cardName(card) {
  return text(card?.name, text(card?.card_id, "Unknown card"));
}

function cardId(card) {
  return text(card?.id, text(card?.card_id, ""));
}

function cardClass(card) {
  return text(card?.class, text(card?.hero_class, text(card?.player_class, t("unknownClass"))));
}

function cardSet(card) {
  return text(card?.card_set, text(card?.set, t("unknownSet")));
}

function artUrl(card) {
  const id = cardId(card);
  return id ? `/catalog/assets/art/${safeId(id)}` : "";
}

function cardArt(card, alt = "") {
  const src = artUrl(card);
  if (!src) {
    return `<div class="arena-card-art is-missing"><span>${escapeHtml(t("missingArt"))}</span></div>`;
  }
  return `<div class="arena-card-art"><img alt="${escapeHtml(alt)}" loading="lazy" data-arena-image data-arena-src="${src}" data-arena-art-id="${escapeHtml(cardId(card))}"></div>`;
}

function normalizeState(payload) {
  const value = payload && typeof payload === "object" ? payload : {};
  return {
    ...value,
    mode: ["setup", "hero", "draft", "ready", "match", "complete"].includes(value.mode) ? value.mode : "setup",
    wins: Number.isFinite(Number(value.wins)) ? Number(value.wins) : 0,
    losses: Number.isFinite(Number(value.losses)) ? Number(value.losses) : 0,
    selected_sets: list(value.selected_sets),
    pack_options: {
      large: list(value.pack_options?.large),
      small: list(value.pack_options?.small),
    },
    hero_offer: list(value.hero_offer),
    card_offer: list(value.card_offer),
    deck: list(value.deck),
  };
}

function currentMode() {
  return model.state?.mode || "setup";
}

function updateCopy() {
  refs.copyNodes.forEach((node) => {
    node.textContent = t(node.dataset.copy);
  });
  document.documentElement.lang = model.locale === "enUS" ? "en" : "zh-CN";
  document.title = `Fireplace · ${t("title")}`;
  refs.localeButtons.forEach((button) => {
    const selected = button.dataset.locale === model.locale;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  renderAccountControls();
}

function updateRecord() {
  const state = model.state || {};
  refs.headerWins.textContent = text(state.wins, "0");
  refs.headerLosses.textContent = text(state.losses, "0");
}

function updateProgress() {
  const order = ["setup", "hero", "draft", "ready"];
  const mode = currentMode();
  const index = mode === "complete" ? order.length : Math.max(0, order.indexOf(mode));
  refs.progress.forEach((node) => {
    const stepIndex = order.indexOf(node.dataset.step);
    node.classList.toggle("is-current", stepIndex === index && mode !== "complete");
    node.classList.toggle("is-complete", stepIndex < index || mode === "complete");
  });
}

function setStatus(message = "") {
  model.status = message;
  refs.status.textContent = message;
}

function setError(message = "") {
  refs.error.textContent = message;
  refs.error.hidden = !message;
}

function setBusy(value) {
  model.busy = Boolean(value);
  refs.stage?.querySelectorAll("button").forEach((button) => {
    const budgetInvalid = button.dataset.action === "start" && selectedBudget(model.state) !== 16;
    button.disabled = model.busy || budgetInvalid || button.dataset.alwaysEnabled === "true";
  });
  const localeLocked = model.state && currentMode() !== "setup";
  refs.localeButtons.forEach((button) => { button.disabled = model.busy || localeLocked; });
  renderAccountControls();
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    cache: "no-store",
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) {
    const serverMessage = payload?.error?.message || payload?.message || payload?.error;
    const failure = new Error(text(serverMessage, `${response.status}`));
    failure.payload = payload;
    failure.status = response.status;
    throw failure;
  }
  return payload;
}

async function post(path, body, progressMessage) {
  if (model.busy) return;
  setError("");
  setStatus(progressMessage || t("waiting"));
  setBusy(true);
  try {
    const payload = await request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    applyState(payload);
  } catch (error) {
    if (error.payload?.mode && error.payload.mode !== "match") applyState(error.payload);
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    setBusy(false);
    setStatus("");
  }
}

function runBody() {
  return {
    run_id: model.state?.run_id,
    revision: model.state?.revision ?? 0,
  };
}

function applyState(payload) {
  const next = normalizeState(payload);
  if (next.mode === "match") {
    // The existing match page owns the board and match session.
    window.location.assign("/?arena=1");
    return;
  }
  model.state = next;
  if (next.mode === "setup" && Array.isArray(next.selected_sets)) {
    model.selectedPacks = new Set(next.selected_sets.filter((value) => text(value) && !["BASIC", "EXPERT1"].includes(text(value))));
  }
  refs.loading.hidden = true;
  refs.stage.hidden = false;
  updateRecord();
  updateProgress();
  render();
}

function render() {
  releaseImages();
  updateCopy();
  renderAccountControls();
  updateRecord();
  updateProgress();
  const state = model.state || normalizeState({ mode: "setup" });
  if (state.mode === "setup") refs.stage.innerHTML = renderSetup(state);
  else if (state.mode === "hero") refs.stage.innerHTML = renderHeroStage(state);
  else if (state.mode === "draft") refs.stage.innerHTML = renderDraftStage(state);
  else if (state.mode === "ready") refs.stage.innerHTML = renderReadyStage(state);
  else if (state.mode === "complete") refs.stage.innerHTML = renderCompleteStage(state);
  else refs.stage.innerHTML = renderSetup(state);
  bindImages();
  setBusy(model.busy);
}

function packOption(option, size) {
  const id = text(option?.id);
  if (!id) return "";
  const selected = model.selectedPacks.has(id);
  const count = numberOrDash(option?.count);
  const label = text(option?.label, id);
  const weight = size === "large" ? 3 : 1;
  return `
    <button class="arena-pack-card${selected ? " is-selected" : ""}" type="button"
      data-action="toggle-pack" data-pack-id="${escapeHtml(id)}" data-pack-size="${size}"
      aria-pressed="${selected}" aria-label="${escapeHtml(label)} · ${weight} ${escapeHtml(t("points"))}">
      <span class="arena-pack-check" aria-hidden="true">${selected ? "✓" : ""}</span>
      <span class="arena-pack-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(count)} ${escapeHtml(t("cards"))}</small></span>
      <span class="arena-pack-weight">${weight} ${escapeHtml(t("points"))}</span>
    </button>`;
}

function selectedBudget(state) {
  const all = [...model.selectedPacks];
  const large = new Set(list(state.pack_options.large).map((option) => text(option?.id)));
  return all.reduce((total, id) => total + (large.has(id) ? 3 : 1), 0);
}

function renderSetup(state) {
  const budget = selectedBudget(state);
  const ready = budget === 16;
  const large = list(state.pack_options.large).map((option) => packOption(option, "large")).join("");
  const small = list(state.pack_options.small).map((option) => packOption(option, "small")).join("");
  const storedName = (() => {
    try { return localStorage.getItem(nicknameStorageKey()) || model.account?.username || ""; } catch (_error) { return model.account?.username || ""; }
  })();
  return `
    <div class="arena-layout arena-setup-layout">
      <section class="arena-panel arena-setup-panel" aria-labelledby="arena-setup-title">
        <div class="arena-panel-heading">
          <div><p class="eyebrow">POOL CONFIGURATION</p><h2 id="arena-setup-title">${escapeHtml(t("setupTitle"))}</h2></div>
          <span class="arena-panel-number">01</span>
        </div>
        <p class="arena-lead">${escapeHtml(t("setupIntro"))}</p>
        <div class="arena-field">
          <label for="arena-nickname">${escapeHtml(t("nickname"))}</label>
          <input id="arena-nickname" type="text" maxlength="24" autocomplete="nickname" value="${escapeHtml(storedName)}" placeholder="${escapeHtml(t("nicknamePlaceholder"))}" data-testid="arena-nickname">
          <small>${escapeHtml(t("nicknameHint"))}</small>
        </div>
        <div class="arena-basic-lock" data-testid="arena-basic-lock">
          <span class="arena-basic-seal" aria-hidden="true">B</span>
          <span><strong>${escapeHtml(t("basicLocked"))}</strong><small>${escapeHtml(t("basicDescription"))}</small></span>
          <span class="arena-lock-icon" aria-hidden="true">⌑</span>
        </div>
        <div class="arena-basic-lock" data-testid="arena-classic-lock">
          <span class="arena-basic-seal" aria-hidden="true">C</span>
          <span><strong>${escapeHtml(t("classicLocked"))}</strong><small>${escapeHtml(t("classicDescription"))}</small></span>
          <span class="arena-lock-icon" aria-hidden="true">⌑</span>
        </div>
        <div class="arena-pack-group">
          <div class="arena-group-heading"><h3>${escapeHtml(t("largePacks"))}</h3><span>3 ${escapeHtml(t("points"))} / ${escapeHtml(t("cards"))}</span></div>
          <div class="arena-pack-grid" data-testid="arena-pack-large">${large || `<p class="arena-empty-copy">${escapeHtml(t("unknownSet"))}</p>`}</div>
        </div>
        <div class="arena-pack-group">
          <div class="arena-group-heading"><h3>${escapeHtml(t("smallPacks"))}</h3><span>1 ${escapeHtml(t("points"))} / ${escapeHtml(t("cards"))}</span></div>
          <div class="arena-pack-grid" data-testid="arena-pack-small">${small || `<p class="arena-empty-copy">${escapeHtml(t("unknownSet"))}</p>`}</div>
        </div>
        <p class="arena-rule-note">${escapeHtml(t("budgetRule"))}</p>
      </section>
      <aside class="arena-panel arena-budget-panel" aria-labelledby="arena-budget-title">
        <div class="arena-budget-ring${ready ? " is-ready" : ""}" aria-label="${escapeHtml(t("budget"))}: ${budget} / 16">
          <strong>${budget}</strong><span>/ 16</span>
        </div>
        <p class="eyebrow">ARENA POOL</p>
        <h2 id="arena-budget-title">${escapeHtml(t("budget"))}</h2>
        <p class="arena-budget-copy">${escapeHtml(ready ? t("budgetReady") : t("budgetInvalid"))}</p>
        <p class="arena-selected-count"><span>${escapeHtml(t("selectedPacks"))}</span><strong>${model.selectedPacks.size}</strong></p>
        <button class="primary-button arena-action-button" type="button" data-action="start" data-testid="arena-start" ${ready ? "" : "disabled"}>${escapeHtml(t("startArena"))}</button>
      </aside>
    </div>`;
}

function renderChoiceCard(card, kind) {
  const id = cardId(card);
  const name = cardName(card);
  const textValue = text(card?.text, t("noText"));
  const cost = card?.cost === undefined ? "" : `<span class="arena-card-cost">${escapeHtml(numberOrDash(card.cost))}</span>`;
  const stats = [
    card?.attack === undefined ? "" : `<span>${escapeHtml(t("attack"))} ${escapeHtml(numberOrDash(card.attack))}</span>`,
    card?.health === undefined ? "" : `<span>${escapeHtml(t("health"))} ${escapeHtml(numberOrDash(card.health))}</span>`,
  ].filter(Boolean).join("");
  const script = card?.has_python_script === true || card?.has_script === true;
  return `
    <article class="arena-choice-card" data-card-id="${escapeHtml(id)}">
      <button class="arena-choice-button" type="button" data-action="${kind === "hero" ? "choose-hero" : "pick-card"}" data-choice-id="${escapeHtml(id)}" aria-label="${escapeHtml(name)}">
        <div class="arena-choice-art-wrap">${cardArt(card, name)}${cost}</div>
        <div class="arena-choice-copy">
          <div class="arena-choice-title"><h3>${escapeHtml(name)}</h3>${stats ? `<span class="arena-card-stats">${stats}</span>` : ""}</div>
          <p class="arena-card-meta"><span>${escapeHtml(cardClass(card))}</span><span>${escapeHtml(cardSet(card))}</span></p>
          <p class="arena-card-text">${escapeHtml(textValue)}</p>
          ${kind === "card" ? `<span class="arena-script-badge ${script ? "has-script" : "no-script"}">${escapeHtml(script ? t("scriptYes") : t("scriptNo"))}</span>` : ""}
          <span class="arena-choice-cta">${escapeHtml(kind === "hero" ? t("chooseHero") : t("pickCard"))} <span aria-hidden="true">→</span></span>
        </div>
      </button>
    </article>`;
}

function heroSummary(hero) {
  if (!hero) return "";
  return `<div class="arena-hero-summary">${cardArt(hero, cardName(hero))}<div><p class="eyebrow">${escapeHtml(t("chosenHero"))}</p><h3>${escapeHtml(cardName(hero))}</h3><p>${escapeHtml(cardClass(hero))} · ${escapeHtml(cardSet(hero))}</p></div></div>`;
}

function renderHeroStage(state) {
  const offers = list(state.hero_offer).map((hero) => renderChoiceCard(hero, "hero")).join("");
  return `
    <div class="arena-layout arena-flow-layout">
      <section class="arena-panel arena-flow-panel" aria-labelledby="arena-hero-title">
        <div class="arena-panel-heading"><div><p class="eyebrow">HERO SELECTION</p><h2 id="arena-hero-title">${escapeHtml(t("heroTitle"))}</h2></div><span class="arena-panel-number">02</span></div>
        <p class="arena-lead">${escapeHtml(t("heroIntro"))}</p>
        <div class="arena-offer-grid arena-hero-offers" data-testid="arena-hero-offer">${offers || `<p class="arena-empty-copy">${escapeHtml(t("waiting"))}</p>`}</div>
      </section>
      <aside class="arena-panel arena-side-panel"><p class="eyebrow">ARENA POOL</p><h2>${escapeHtml(t("selectedPacks"))}</h2>${renderSelectedPacks(state)}${heroSummary(state.hero)}</aside>
    </div>`;
}

function renderSelectedPacks(state) {
  const selected = list(state.selected_sets).filter((set) => !["BASIC", "EXPERT1"].includes(text(set)));
  return `<div class="arena-selected-packs"><span class="arena-basic-chip">BASIC</span><span class="arena-basic-chip">${escapeHtml(t("classicLocked"))}</span>${selected.map((set) => `<span>${escapeHtml(text(set))}</span>`).join("")}</div>`;
}

function manaCost(card) {
  const raw = card?.cost;
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? Math.trunc(value) : null;
}

function renderManaCurve(deck) {
  const counts = Array(8).fill(0);
  deck.forEach((card) => {
    const cost = manaCost(card);
    if (cost !== null) counts[Math.min(cost, 7)] += 1;
  });
  const largest = Math.max(1, ...counts);
  const bars = counts.map((count, index) => {
    const label = index === 7 ? "7+" : String(index);
    const height = Math.round((count / largest) * 100);
    return `<li class="arena-mana-column" data-mana-bucket="${label}" data-count="${count}" aria-label="${escapeHtml(t("manaBucket", { cost: label, count }))}">
      <span class="arena-mana-count">${count}</span>
      <span class="arena-mana-track"><span class="arena-mana-fill" style="height: ${height}%"></span></span>
      <span class="arena-mana-label">${label}</span>
    </li>`;
  }).join("");
  return `<section class="arena-mana-curve" data-testid="arena-mana-curve" aria-label="${escapeHtml(t("manaCurve"))}">
    <h3>${escapeHtml(t("manaCurve"))}</h3><ol class="arena-mana-bars">${bars}</ol>
  </section>`;
}

function renderDeck(state) {
  const deck = list(state.deck);
  const sorted = deck.map((card, index) => ({ card, index, cost: manaCost(card) }))
    .sort((first, second) => (first.cost ?? Infinity) - (second.cost ?? Infinity) || first.index - second.index);
  const rows = sorted.map(({ card, cost }, index) => `
    <li class="arena-deck-row">
      <span class="arena-deck-index">${index + 1}</span>
      <span class="arena-deck-cost" data-card-cost="${cost === null ? "" : cost}">${escapeHtml(numberOrDash(card?.cost))}</span>
      <span class="arena-deck-name">${escapeHtml(cardName(card))}</span>
      <span class="arena-deck-set">${escapeHtml(cardSet(card))}</span>
    </li>`).join("");
  return `<section class="arena-deck-panel" aria-labelledby="arena-deck-title"><div class="arena-deck-heading"><h2 id="arena-deck-title">${escapeHtml(t("deckTitle"))}</h2><strong>${escapeHtml(t("deckCount", { count: deck.length }))}</strong></div>${state.hero ? heroSummary(state.hero) : ""}${renderManaCurve(deck)}<ol class="arena-deck-list" data-testid="arena-deck">${rows || `<li class="arena-muted">${escapeHtml(t("waiting"))}</li>`}</ol></section>`;
}

function renderDraftStage(state) {
  const deck = list(state.deck);
  const offers = list(state.card_offer).map((card) => renderChoiceCard(card, "card")).join("");
  return `
    <div class="arena-layout arena-draft-layout">
      <section class="arena-panel arena-flow-panel" aria-labelledby="arena-draft-title">
        <div class="arena-panel-heading"><div><p class="eyebrow">CARD DRAFT</p><h2 id="arena-draft-title">${escapeHtml(t("draftTitle"))}</h2></div><span class="arena-panel-number">03</span></div>
        <p class="arena-lead">${escapeHtml(t("draftIntro"))}</p>
        <p class="arena-draft-progress" data-testid="arena-draft-count">${escapeHtml(t("draftProgress", { current: deck.length + 1, total: 30 }))}</p>
        <div class="arena-offer-grid arena-card-offers" data-testid="arena-card-offer">${offers || `<p class="arena-empty-copy">${escapeHtml(t("waiting"))}</p>`}</div>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function renderReadyStage(state) {
  return `
    <div class="arena-layout arena-ready-layout">
      <section class="arena-panel arena-ready-panel" aria-labelledby="arena-ready-title">
        <div class="arena-panel-heading"><div><p class="eyebrow">DECK COMPLETE</p><h2 id="arena-ready-title">${escapeHtml(t("readyTitle"))}</h2></div><span class="arena-panel-number">04</span></div>
        <p class="arena-lead">${escapeHtml(t("readyIntro"))}</p>
        ${heroSummary(state.hero)}
        <div class="arena-ready-record"><span>${escapeHtml(t("wins"))}</span><strong>${escapeHtml(text(state.wins, "0"))}</strong><span>${escapeHtml(t("losses"))}</span><strong>${escapeHtml(text(state.losses, "0"))}</strong></div>
        <button class="primary-button arena-action-button" type="button" data-action="battle" data-testid="arena-battle">${escapeHtml(t("enterBattle"))}</button>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function renderCompleteStage(state) {
  return `
    <div class="arena-layout arena-complete-layout">
      <section class="arena-panel arena-complete-panel" aria-labelledby="arena-complete-title">
        <span class="arena-complete-sigil" aria-hidden="true">✦</span>
        <p class="eyebrow">ARENA RUN COMPLETE</p>
        <h2 id="arena-complete-title">${escapeHtml(t("completeTitle"))}</h2>
        <p class="arena-lead">${escapeHtml(t("completeIntro"))}</p>
        <div class="arena-final-record"><span>${escapeHtml(t("wins"))}</span><strong>${escapeHtml(text(state.wins, "0"))}</strong><i>/</i><strong>${escapeHtml(text(state.losses, "0"))}</strong><span>${escapeHtml(t("losses"))}</span></div>
        <button class="primary-button arena-action-button" type="button" data-action="reset" data-testid="arena-reset">${escapeHtml(t("startAgain"))}</button>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function bindImages() {
  refs.stage.querySelectorAll("img[data-arena-image]").forEach((image) => {
    image.dataset.imageState = "loading";
    void loadImage(image);
  });
}

function releaseImages() {
  model.imageGeneration += 1;
  model.imageUrls.forEach((url) => URL.revokeObjectURL(url));
  model.imageUrls.clear();
}

function markImageMissing(image) {
  image.dataset.imageState = "failed";
  const wrapper = image.closest(".arena-card-art");
  wrapper?.classList.add("is-missing");
  image.remove();
  if (wrapper && !wrapper.textContent.trim()) {
    const label = document.createElement("span");
    label.textContent = t("missingArt");
    wrapper.append(label);
  }
}

async function loadImage(image) {
  const generation = model.imageGeneration;
  const src = image.dataset.arenaSrc;
  if (!src) {
    markImageMissing(image);
    return;
  }
  const delays = [250, 750, 1500, 3000, 5000];
  for (let attempt = 0; attempt < delays.length + 1; attempt += 1) {
    if (generation !== model.imageGeneration) return;
    try {
      const response = await fetch(src, { cache: "no-store" });
      if (response.ok && response.status !== 202 && response.status !== 204) {
        const blob = await response.blob();
        if (generation !== model.imageGeneration) return;
        const objectUrl = URL.createObjectURL(blob);
        model.imageUrls.add(objectUrl);
        image.onerror = () => {
          if (generation === model.imageGeneration) markImageMissing(image);
        };
        image.src = objectUrl;
        image.dataset.imageState = "loaded";
        return;
      }
      if (response.status !== 202 && response.status !== 204 && response.status !== 429 && response.status < 500) break;
    } catch (_error) {
      // A temporary asset-server failure is retried with the same policy as 202.
    }
    if (attempt < delays.length) await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
  }
  markImageMissing(image);
}

function selectedNickname() {
  const input = document.getElementById("arena-nickname");
  const value = text(input?.value).trim();
  if (value) {
    try { localStorage.setItem(nicknameStorageKey(), value); } catch (_error) { /* noop */ }
  }
  return value;
}

async function handleAction(actionNode) {
  const action = actionNode.dataset.action;
  if (action === "toggle-pack") {
    const id = text(actionNode.dataset.packId);
    if (!id || model.busy) return;
    if (model.selectedPacks.has(id)) model.selectedPacks.delete(id);
    else model.selectedPacks.add(id);
    render();
    return;
  }
  if (action === "start") {
    const nickname = selectedNickname();
    if (!nickname) {
      setError(t("invalidName"));
      document.getElementById("arena-nickname")?.focus();
      return;
    }
    if (selectedBudget(model.state) !== 16) {
      setError(t("invalidBudget"));
      return;
    }
    await post("/api/arena/start", { nickname, locale: model.locale, set_ids: [...model.selectedPacks] }, t("starting"));
    return;
  }
  if (action === "choose-hero") {
    await post("/api/arena/hero", { ...runBody(), hero_id: text(actionNode.dataset.choiceId) }, t("waiting"));
    return;
  }
  if (action === "pick-card") {
    await post("/api/arena/pick", { ...runBody(), card_id: text(actionNode.dataset.choiceId) }, t("waiting"));
    return;
  }
  if (action === "battle") {
    await post("/api/arena/battle", runBody(), t("launching"));
    return;
  }
  if (action === "reset") {
    await post("/api/arena/reset", runBody(), t("waiting"));
  }
}

refs.stage.addEventListener("click", (event) => {
  const actionNode = event.target.closest("[data-action]");
  if (!actionNode || !refs.stage.contains(actionNode)) return;
  event.preventDefault();
  void handleAction(actionNode);
});

refs.stage.addEventListener("input", (event) => {
  if (event.target.id === "arena-nickname") {
    try { localStorage.setItem(nicknameStorageKey(), text(event.target.value)); } catch (_error) { /* noop */ }
  }
});

refs.localeButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    if (model.busy || !COPY[button.dataset.locale] || (model.state && currentMode() !== "setup")) return;
    const previousPacks = new Set(model.selectedPacks);
    model.locale = button.dataset.locale;
    storeLocale(model.locale);
    updateCopy();
    setError("");
    setStatus(t("loading"));
    setBusy(true);
    try {
      const payload = await request(`/api/arena/state?locale=${encodeURIComponent(model.locale)}`);
      applyState(payload);
      if (model.state?.mode === "setup" && model.state.selected_sets.length === 0) {
        model.selectedPacks = previousPacks;
        render();
      }
      setStatus("");
    } catch (error) {
      setError(t("requestFailed", { message: error.message || t("network") }));
      setStatus("");
    } finally {
      setBusy(false);
    }
  });
});

refs.accountLogout.addEventListener("click", () => { void logoutAccount(); });
refs.accountImport.addEventListener("click", () => { void importLegacy(); });

updateCopy();
setStatus(t("loading"));

void (async () => {
  if (!(await loadAccountSession())) return;
  watchAccountSession(model.account.id, () => { window.location.replace(accountUrl()); });
  try {
    const payload = await request(`/api/arena/state?locale=${encodeURIComponent(model.locale)}`);
    setStatus("");
    applyState(payload);
  } catch (error) {
    refs.loading.hidden = true;
    refs.stage.hidden = false;
    model.state = normalizeState({ mode: "setup" });
    render();
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  }
})();
