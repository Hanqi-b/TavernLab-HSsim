import { announceAccountChange, watchAccountSession } from "./account_session.js";
import { createStaticCardFace, createStaticCardFaceManager } from "./card_face.js";

/*
 * Collection composition root.
 *
 * The server owns deck validation and revisions.  This page keeps only the
 * current editor state and asks the catalog endpoint for searchable card
 * metadata.  No game-engine objects are imported into this browser flow.
 */

const PAGE_SIZE = 48;

const COPY = {
  zhCN: {
    back: "返回开始界面",
    title: "收藏",
    subtitle: "管理卡组，准备下一场对战。",
    browseCards: "浏览可收藏卡牌",
    language: "界面语言",
    loading: "正在读取收藏……",
    deckList: "我的卡组",
    newDeck: "新建卡组",
    noDecks: "还没有卡组，先创建一个吧。",
    chooseDeck: "选择一个卡组开始编辑",
    chooseDeckCopy: "你可以保存空卡组，之后再慢慢补齐。",
    editDeck: "编辑卡组",
    useInBattle: "用于对战",
    deleteDeck: "删除卡组",
    saveDeck: "保存卡组",
    deckName: "卡组名称",
    chooseHero: "选择英雄",
    heroHint: "英雄决定职业卡筛选。",
    addCards: "添加卡牌",
    chooseHeroFirst: "请先选择英雄",
    searchCards: "搜索卡牌",
    classCards: "职业牌",
    neutralCards: "中立牌",
    noCards: "没有符合条件的卡牌。",
    previous: "上一页",
    next: "下一页",
    selectedCards: "已选卡牌",
    manaCurve: "法力曲线",
    noSelectedCards: "还没有加入卡牌。",
    heroUnset: "未选择英雄",
    cards: "张牌",
    complete: "已完成",
    incomplete: "未完成",
    remove: "移除",
    add: "加入卡组",
    cardAdded: "已加入 {name}，卡组现有 {count} / 30 张。",
    cardRemoved: "已移除 {name}，卡组现有 {count} / 30 张。",
    inspect: "查看详情",
    close: "关闭",
    cardDetails: "卡牌详情",
    duplicateLimit: "普通牌最多两张，传说牌最多一张。",
    deckFull: "卡组已满 30 张。",
    saved: "卡组已保存。",
    deleted: "卡组已删除。",
    newDeckName: "新卡组",
    page: "第 {current} / {total} 页",
    noHeroCards: "暂无符合职业的卡牌。",
    requestFailed: "请求失败：{message}",
    network: "无法连接本机收藏服务。",
    saving: "正在保存……",
    deleting: "正在删除……",
    loadingCards: "正在读取卡牌……",
    loadingDecks: "正在读取收藏……",
    invalidName: "请输入卡组名称。",
    heroRequired: "请选择一个英雄后再加入职业牌。",
    chooseHeroToSave: "请选择英雄后再保存卡组。",
    selectHero: "选择此英雄",
    cost: "费用",
    rarity: "稀有度",
    attack: "攻击",
    health: "生命",
    durability: "耐久",
    rules: "卡牌文字",
    noText: "暂无卡牌文字。",
    cardImage: "卡牌图片",
    loadingImage: "正在读取卡牌……",
    imagePending: "卡牌图像仍在准备中。",
    imageUnavailable: "卡牌图像暂不可用。",
    unknownCard: "未知卡牌",
    unsaved: "当前卡组有未保存的修改。",
    discard: "放弃未保存的修改吗？",
    heroChange: "更换英雄会清空当前已选卡牌，继续吗？",
    savedHeroChange: "更换英雄会新建一个空卡组，并保留当前已保存的卡组；未保存的修改不会带入新卡组。继续吗？",
  },
  enUS: {
    back: "Back to start",
    title: "Collection",
    subtitle: "Manage decks and prepare your next match.",
    browseCards: "Browse collectible cards",
    language: "Language",
    loading: "Loading collection…",
    deckList: "My decks",
    newDeck: "New",
    noDecks: "No decks yet. Create one to get started.",
    chooseDeck: "Choose a deck to edit",
    chooseDeckCopy: "You can save an empty deck and fill it later.",
    editDeck: "Edit deck",
    useInBattle: "Use in battle",
    deleteDeck: "Delete deck",
    saveDeck: "Save deck",
    deckName: "Deck name",
    chooseHero: "Choose a hero",
    heroHint: "Your hero controls the class filter.",
    addCards: "Add cards",
    chooseHeroFirst: "Choose a hero first",
    searchCards: "Search cards",
    classCards: "Class cards",
    neutralCards: "Neutral",
    noCards: "No cards match these filters.",
    previous: "Previous",
    next: "Next",
    selectedCards: "Selected cards",
    manaCurve: "Mana curve",
    noSelectedCards: "No cards have been added.",
    heroUnset: "No hero selected",
    cards: "cards",
    complete: "Complete",
    incomplete: "Incomplete",
    remove: "Remove",
    add: "Add to deck",
    cardAdded: "Added {name}. Deck now has {count} / 30 cards.",
    cardRemoved: "Removed {name}. Deck now has {count} / 30 cards.",
    inspect: "View details",
    close: "Close",
    cardDetails: "Card details",
    duplicateLimit: "Up to two copies of a normal card and one legendary copy.",
    deckFull: "The deck already has 30 cards.",
    saved: "Deck saved.",
    deleted: "Deck deleted.",
    newDeckName: "New deck",
    page: "Page {current} / {total}",
    noHeroCards: "No class cards match these filters.",
    requestFailed: "Request failed: {message}",
    network: "The local collection service is unavailable.",
    saving: "Saving…",
    deleting: "Deleting…",
    loadingCards: "Loading cards…",
    loadingDecks: "Loading collection…",
    invalidName: "Enter a deck name.",
    heroRequired: "Choose a hero before adding class cards.",
    chooseHeroToSave: "Choose a hero before saving the deck.",
    selectHero: "Choose this hero",
    cost: "Cost",
    rarity: "Rarity",
    attack: "Attack",
    health: "Health",
    durability: "Durability",
    rules: "Card text",
    noText: "No card text available.",
    cardImage: "card image",
    loadingImage: "Loading card render…",
    imagePending: "The card render is still preparing.",
    imageUnavailable: "The card render is unavailable.",
    unknownCard: "Unknown card",
    unsaved: "This deck has unsaved changes.",
    discard: "Discard unsaved changes?",
    heroChange: "Changing hero will clear the selected cards. Continue?",
    savedHeroChange: "Changing hero creates a new empty deck and preserves the saved deck. Unsaved edits will not carry over. Continue?",
  },
};

const refs = {
  app: document.getElementById("collection-app"),
  status: document.getElementById("collection-status"),
  error: document.getElementById("collection-error"),
  loading: document.getElementById("collection-loading"),
  layout: document.getElementById("collection-layout"),
  deckList: document.getElementById("deck-list"),
  deckEmpty: document.getElementById("deck-empty"),
  editorEmpty: document.getElementById("editor-empty"),
  editor: document.getElementById("collection-editor"),
  name: document.getElementById("deck-name"),
  heroGrid: document.getElementById("hero-grid"),
  cardSearch: document.getElementById("card-search"),
  clearSearch: document.querySelector(".collection-clear-search"),
  cardFilterHint: document.getElementById("card-filter-hint"),
  classTabs: [...document.querySelectorAll("[data-action=class-scope]")],
  cardGrid: document.getElementById("card-grid"),
  cardEmpty: document.getElementById("card-empty"),
  cardPagination: document.getElementById("card-pagination"),
  cardPageLabel: document.getElementById("card-page-label"),
  previousPage: document.querySelector("[data-action=previous-page]"),
  nextPage: document.querySelector("[data-action=next-page]"),
  selectedTitle: document.getElementById("selected-title"),
  cardCount: document.getElementById("card-count"),
  manaBars: document.getElementById("mana-bars"),
  selectedList: document.getElementById("selected-list"),
  selectedEmpty: document.getElementById("selected-empty"),
  battleLink: document.getElementById("collection-battle-link"),
  cardDialog: document.getElementById("collection-card-dialog"),
  cardDialogClose: document.getElementById("collection-card-detail-close"),
  cardDetailFace: document.getElementById("collection-card-detail-face"),
  cardDetailEyebrow: document.getElementById("collection-card-detail-eyebrow"),
  cardDetailName: document.getElementById("collection-card-detail-name"),
  cardDetailId: document.getElementById("collection-card-detail-id"),
  cardDetailStats: document.getElementById("collection-card-detail-stats"),
  cardDetailRulesTitle: document.getElementById("collection-card-detail-rules-title"),
  cardDetailText: document.getElementById("collection-card-detail-text"),
  accountToolbar: document.getElementById("collection-account-toolbar"),
  accountLabel: document.getElementById("collection-account-label"),
  accountImport: document.getElementById("collection-account-import"),
  accountLogout: document.getElementById("collection-account-logout"),
  localeButtons: [...document.querySelectorAll("[data-locale]")],
  copyNodes: [...document.querySelectorAll("[data-copy]")],
};

const model = {
  locale: readLocale(),
  decks: [],
  heroes: [],
  editor: null,
  selectedDeckId: null,
  cards: [],
  totalCards: 0,
  cardPage: 1,
  cardPageSize: PAGE_SIZE,
  classScope: "class",
  search: "",
  requestNumber: 0,
  cardRequestNumber: 0,
  cardTimer: null,
  busy: false,
  dirty: false,
  account: null,
  legacyAvailable: false,
  heroFaceManager: null,
  cardFaceManager: null,
  cardDetailFaceManager: null,
  cardDetailPreviousFocus: null,
};

function text(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function escapeHtml(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function t(key, variables = {}) {
  const value = COPY[model.locale]?.[key] ?? COPY.zhCN[key] ?? key;
  return String(value).replace(/\{(\w+)\}/g, (_match, name) => String(variables[name] ?? ""));
}

function staticCardFaceCopy() {
  return {
    cost: t("cost"),
    attack: t("attack"),
    health: t("health"),
    durability: t("durability"),
    rules: t("rules"),
    noRules: t("noText"),
    loading: t("loadingImage"),
    pending: t("imagePending"),
    unavailable: t("imageUnavailable"),
    cardImage: t("cardImage"),
    unknownCard: t("unknownCard"),
  };
}

function readLocale() {
  try {
    return localStorage.getItem("fireplace.locale") === "enUS" ? "enUS" : "zhCN";
  } catch (_error) {
    return "zhCN";
  }
}

function saveLocale(locale) {
  try { localStorage.setItem("fireplace.locale", locale); } catch (_error) { /* private mode */ }
}

function currentPath() {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") ? path : "/collection";
}

function accountUrl() {
  return `/account?next=${encodeURIComponent(currentPath())}`;
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
    await loadDecks(model.selectedDeckId);
  } catch (error) {
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    setBusy(false);
    renderAccountControls();
  }
}

function cardId(card) {
  return text(card?.id, text(card?.card_id, ""));
}

function cardName(card) {
  return text(card?.name, cardId(card) || "Unknown card");
}

function cardCost(card) {
  const value = Number(card?.cost);
  return Number.isFinite(value) && value >= 0 ? Math.trunc(value) : null;
}

function cardRarity(card) {
  return text(card?.rarity).toUpperCase();
}

function isDeckCard(card) {
  const type = text(card?.type).toUpperCase();
  if (!type) return true;
  if (["MINION", "SPELL", "WEAPON"].includes(type)) return true;
  if (type !== "HERO") return false;
  const id = cardId(card);
  const cardSet = text(card?.card_set).toUpperCase();
  const catalogSet = text(card?.catalog_set).toUpperCase();
  return cardSet !== "HERO_SKINS" && catalogSet !== "HEROES" && !id.startsWith("HERO_");
}

function isLegendary(card) {
  return cardRarity(card) === "LEGENDARY";
}

function heroClass(hero) {
  return text(hero?.class, text(hero?.hero_class, text(hero?.player_class, ""))).toUpperCase();
}

function normalizeCard(raw) {
  const value = raw && typeof raw === "object" ? raw : {};
  return { ...value, id: cardId(value) };
}

function normalizeDeck(raw) {
  const value = raw && typeof raw === "object" ? raw : {};
  const ids = list(value.card_ids).map((id) => text(id)).filter(Boolean);
  const cards = list(value.cards).map(normalizeCard);
  const cardsById = new Map(cards.map((card) => [cardId(card), card]));
  const resolvedCards = [];
  const seenCardIds = new Set();
  ids.forEach((id) => {
    if (seenCardIds.has(id)) return;
    seenCardIds.add(id);
    resolvedCards.push(cardsById.get(id) || { id, name: id, cost: null });
  });
  const cardIds = ids.length ? ids : resolvedCards.map(cardId).filter(Boolean);
  return {
    id: text(value.id),
    revision: Number.isInteger(value.revision) ? value.revision : Number(value.revision) || 0,
    name: text(value.name, t("newDeckName")),
    hero_id: text(value.hero_id),
    hero: value.hero ? normalizeCard(value.hero) : null,
    cards: resolvedCards,
    card_ids: cardIds,
    complete: value.complete === true,
  };
}

function normalizeHero(raw) {
  const value = normalizeCard(raw);
  return { ...value, class: heroClass(value) };
}

function normalizePayload(payload) {
  const value = payload && typeof payload === "object" ? payload : {};
  return {
    decks: list(value.decks).map(normalizeDeck),
    heroes: list(value.heroes).map(normalizeHero),
    locale: value.locale === "enUS" ? "enUS" : model.locale,
  };
}

function newDeckName() {
  const base = t("newDeckName");
  const names = new Set(model.decks.map((deck) => text(deck?.name).trim()).filter(Boolean));
  if (!names.has(base)) return base;
  let suffix = 2;
  while (names.has(`${base} ${suffix}`)) suffix += 1;
  return `${base} ${suffix}`;
}

function editorFromDeck(deck) {
  const value = deck ? normalizeDeck(deck) : {
    id: "",
    revision: 0,
    name: newDeckName(),
    hero_id: "",
    hero: null,
    cards: [],
    card_ids: [],
    complete: false,
  };
  return {
    id: value.id,
    revision: value.revision,
    name: value.name,
    hero_id: value.hero_id,
    hero: value.hero || model.heroes.find((hero) => cardId(hero) === value.hero_id) || null,
    cards: value.cards.map(normalizeCard),
    card_ids: value.card_ids.slice(),
    complete: value.complete,
  };
}

function setStatus(message = "") {
  refs.status.textContent = message;
}

function setError(message = "") {
  refs.error.textContent = message;
  refs.error.hidden = !message;
}

function setBusy(value) {
  model.busy = Boolean(value);
  refs.app.querySelectorAll("button, input").forEach((node) => {
    if (node.dataset.locale) node.disabled = model.busy;
  });
  renderAccountControls();
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    cache: "no-store",
  });
  let payload = {};
  try { payload = await response.json(); } catch (_error) { /* empty response */ }
  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || payload?.error || `${response.status}`;
    const error = new Error(text(message, `${response.status}`));
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function applyPayload(payload, preferredId = model.selectedDeckId) {
  const normalized = normalizePayload(payload);
  if (payload?.locale === "enUS" || payload?.locale === "zhCN") model.locale = payload.locale;
  model.decks = normalized.decks;
  model.heroes = normalized.heroes;
  const targetId = preferredId && model.decks.some((deck) => deck.id === preferredId)
    ? preferredId
    : model.decks[0]?.id || null;
  model.selectedDeckId = targetId;
  model.editor = targetId ? editorFromDeck(model.decks.find((deck) => deck.id === targetId)) : null;
  model.dirty = false;
  if (model.editor?.hero_id && !model.editor.hero) {
    model.editor.hero = model.heroes.find((hero) => cardId(hero) === model.editor.hero_id) || null;
  }
  renderAll();
}

async function loadDecks(preferredId = null) {
  setError("");
  setStatus(t("loadingDecks"));
  try {
    const payload = await request(`/api/decks?locale=${encodeURIComponent(model.locale)}`);
    applyPayload(payload, preferredId);
  } catch (error) {
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  }
}

function editorBody(includeIdentity = true) {
  const body = {
    name: text(model.editor?.name).trim(),
    hero_id: text(model.editor?.hero_id),
    card_ids: list(model.editor?.card_ids),
    locale: model.locale,
  };
  if (includeIdentity && model.editor?.id) {
    body.id = model.editor.id;
    body.revision = model.editor.revision;
  }
  return body;
}

async function saveDeck(event) {
  event?.preventDefault();
  if (!model.editor || model.busy) return;
  const name = text(refs.name.value).trim();
  model.editor.name = name;
  if (!name) {
    setError(t("invalidName"));
    refs.name.focus();
    return;
  }
  if (!model.editor.hero_id) {
    setError(t("chooseHeroToSave"));
    return;
  }
  setError("");
  setStatus(t("saving"));
  setBusy(true);
  try {
    const payload = await request("/api/decks/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editorBody()),
    });
    const savedId = text(payload?.saved_id) || text(payload?.deck_id) || payload?.decks?.find?.((deck) => deck.id === model.editor.id)?.id || model.editor.id;
    applyPayload(payload, savedId || null);
    setStatus(t("saved"));
  } catch (error) {
    if (error.payload?.decks) applyPayload(error.payload, model.selectedDeckId);
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    setBusy(false);
  }
}

async function deleteDeck() {
  if (!model.editor?.id || model.busy) return;
  setError("");
  setStatus(t("deleting"));
  setBusy(true);
  try {
    const payload = await request("/api/decks/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: model.editor.id, revision: model.editor.revision, locale: model.locale }),
    });
    applyPayload(payload, null);
    setStatus(t("deleted"));
  } catch (error) {
    if (error.payload?.decks) applyPayload(error.payload, model.selectedDeckId);
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    setBusy(false);
  }
}

function newDeck() {
  if (model.busy) return;
  if (!confirmDiscard()) return;
  model.selectedDeckId = null;
  model.editor = editorFromDeck(null);
  model.dirty = false;
  model.classScope = "class";
  model.search = "";
  model.cardPage = 1;
  refs.cardSearch.value = "";
  setError("");
  setStatus("");
  renderAll();
  refs.name.focus();
  void loadCards();
}

function selectDeck(id) {
  if (model.busy || !id) return;
  if (!confirmDiscard()) return;
  const deck = model.decks.find((item) => item.id === id);
  if (!deck) return;
  model.selectedDeckId = id;
  model.editor = editorFromDeck(deck);
  model.dirty = false;
  model.classScope = "class";
  model.search = "";
  model.cardPage = 1;
  refs.cardSearch.value = "";
  setError("");
  setStatus("");
  renderAll();
  void loadCards();
}

function chooseHero(id) {
  if (!model.editor || model.busy) return;
  const hero = model.heroes.find((item) => cardId(item) === id);
  if (!hero) return;
  if (model.editor.hero_id === id) return;
  const hasSavedDeck = Boolean(model.editor.id);
  const hasCards = model.editor.card_ids.length > 0;
  if (hasSavedDeck) {
    if (!window.confirm(t("savedHeroChange"))) return;
    model.selectedDeckId = null;
    model.editor = editorFromDeck(null);
  } else {
    if (hasCards && !window.confirm(t("heroChange"))) return;
    if (hasCards) {
      model.editor.card_ids = [];
      model.editor.cards = [];
      model.editor.complete = false;
    }
  }
  model.editor.hero_id = id;
  model.editor.hero = hero;
  model.dirty = true;
  model.cardPage = 1;
  setError("");
  renderAll();
  void loadCards();
}

function cardCopies(id) {
  return list(model.editor?.card_ids).filter((cardIdValue) => cardIdValue === id).length;
}

function canAddCard(card) {
  if (!model.editor || !cardId(card)) return { ok: false, reason: t("noCards") };
  if (model.editor.card_ids.length >= 30) return { ok: false, reason: t("deckFull") };
  const copies = cardCopies(cardId(card));
  const limit = isLegendary(card) ? 1 : 2;
  if (copies >= limit) return { ok: false, reason: t("duplicateLimit") };
  return { ok: true, reason: "" };
}

function findCardActionButton(action, id, root = refs.app) {
  return [...root.querySelectorAll(`[data-action="${action}"]`)]
    .find((button) => button.dataset.cardId === id) || null;
}

function captureCardFocus() {
  const active = document.activeElement;
  const actionButton = active?.closest?.("[data-action]");
  if (!actionButton || !refs.app.contains(actionButton)) return null;
  const action = actionButton.dataset.action;
  if (action !== "add-card" && action !== "remove-card") return null;
  const id = actionButton.dataset.cardId;
  if (!id) return null;
  const removeButtons = action === "remove-card"
    ? [...refs.selectedList.querySelectorAll('[data-action="remove-card"]')]
    : [];
  return {
    action,
    id,
    index: removeButtons.indexOf(actionButton),
  };
}

function restoreCardFocus(context) {
  if (!context) return;
  let target = null;
  if (context.action === "add-card") {
    target = findCardActionButton("add-card", context.id, refs.cardGrid);
    if (target?.disabled) target = findCardActionButton("remove-card", context.id, refs.selectedList);
  } else {
    target = findCardActionButton("remove-card", context.id, refs.selectedList);
    if (!target) {
      const removeButtons = [...refs.selectedList.querySelectorAll('[data-action="remove-card"]')];
      target = removeButtons[Math.min(Math.max(context.index, 0), removeButtons.length - 1)] || null;
      if (!target) target = findCardActionButton("add-card", context.id, refs.cardGrid);
    }
  }
  if (target && !target.disabled) target.focus();
}

function refreshCardOptionAvailability() {
  if (!model.editor) return;
  const cardsById = new Map(model.cards.map((card) => [cardId(card), card]));
  refs.cardGrid.querySelectorAll('[data-action="add-card"]').forEach((button) => {
    const card = cardsById.get(button.dataset.cardId);
    if (!card) return;
    const result = canAddCard(card);
    const disabled = !result.ok;
    button.disabled = disabled;
    button.classList.toggle("is-unavailable", disabled);
    if (disabled) button.setAttribute("aria-disabled", "true");
    else button.removeAttribute("aria-disabled");
    button.setAttribute(
      "aria-label",
      disabled ? `${cardName(card)} · ${result.reason}` : `${t("add")}: ${cardName(card)}`,
    );
  });
}

function refreshEditorAfterCardChange() {
  const focus = captureCardFocus();
  renderSelectedCards();
  renderBattleLink();
  refreshCardOptionAvailability();
  restoreCardFocus(focus);
}

function numericCardValue(card, ...keys) {
  for (const key of keys) {
    if (card?.[key] === null || card?.[key] === undefined || card?.[key] === "") continue;
    const value = Number(card?.[key]);
    if (Number.isFinite(value)) return Math.trunc(value);
  }
  return null;
}

function cardDetailStats(card) {
  const stats = [{ label: t("cost"), value: cardCost(card) }];
  const type = text(card?.type).toUpperCase();
  if (type === "WEAPON") {
    stats.push(
      { label: t("attack"), value: numericCardValue(card, "attack", "atk", "printed_atk") },
      { label: t("durability"), value: numericCardValue(card, "durability", "max_durability", "printed_durability") },
    );
  } else if (type === "MINION" || type === "HERO") {
    stats.push(
      { label: t("attack"), value: numericCardValue(card, "attack", "atk", "printed_atk") },
      { label: t("health"), value: numericCardValue(card, "health", "max_health", "printed_health") },
    );
  }
  return stats;
}

function renderCardDetail(card) {
  refs.cardDialogClose.setAttribute("aria-label", t("close"));
  refs.cardDetailEyebrow.textContent = t("cardDetails");
  refs.cardDetailName.textContent = cardName(card);
  refs.cardDetailId.textContent = cardId(card);
  refs.cardDetailRulesTitle.textContent = t("rules");
  refs.cardDetailText.textContent = text(card?.text, text(card?.rulesText, t("noText")));
  refs.cardDetailStats.replaceChildren();
  cardDetailStats(card).forEach(({ label, value }) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value === null ? "—" : String(value);
    refs.cardDetailStats.append(term, description);
  });
}

function clearCardDetail() {
  model.cardDetailFaceManager?.release();
  model.cardDetailFaceManager = null;
  refs.cardDetailFace.replaceChildren();
  const previousFocus = model.cardDetailPreviousFocus;
  model.cardDetailPreviousFocus = null;
  if (previousFocus?.isConnected && typeof previousFocus.focus === "function") previousFocus.focus();
}

function closeCardDetail() {
  if (refs.cardDialog?.open && typeof refs.cardDialog.close === "function") refs.cardDialog.close();
  else refs.cardDialog?.removeAttribute("open");
  clearCardDetail();
}

function inspectCard(id) {
  const card = model.cards.find((item) => cardId(item) === id);
  if (!card || !refs.cardDialog) return;
  model.cardDetailPreviousFocus = document.activeElement;
  model.cardDetailFaceManager?.release();
  model.cardDetailFaceManager = createStaticCardFaceManager({
    locale: model.locale,
    copy: staticCardFaceCopy(),
  });
  renderCardDetail(card);
  const face = createStaticCardFace(card, {
    locale: model.locale,
    copy: staticCardFaceCopy(),
    eager: true,
    className: "collection-card-detail-face-card",
  });
  refs.cardDetailFace.replaceChildren(face);
  model.cardDetailFaceManager.observe(face, card, { eager: true });
  if (typeof refs.cardDialog.showModal === "function" && !refs.cardDialog.open) refs.cardDialog.showModal();
  else refs.cardDialog.setAttribute("open", "");
  refs.cardDialogClose.focus();
}

function addCard(card) {
  if (!model.editor || model.busy) return;
  const value = normalizeCard(card);
  const result = canAddCard(value);
  if (!result.ok) {
    setError(result.reason);
    return;
  }
  model.editor.card_ids.push(cardId(value));
  const existing = model.editor.cards.find((item) => cardId(item) === cardId(value));
  if (!existing) model.editor.cards.push(value);
  model.editor.complete = model.editor.card_ids.length === 30;
  model.dirty = true;
  setError("");
  refreshEditorAfterCardChange();
  setStatus(t("cardAdded", { name: cardName(value), count: model.editor.card_ids.length }));
}

function removeCard(id) {
  if (!model.editor || model.busy) return;
  const index = model.editor.card_ids.indexOf(id);
  if (index < 0) return;
  const removedCard = model.editor.cards.find((card) => cardId(card) === id);
  model.editor.card_ids.splice(index, 1);
  model.editor.complete = false;
  model.dirty = true;
  refreshEditorAfterCardChange();
  setStatus(t("cardRemoved", { name: removedCard ? cardName(removedCard) : id, count: model.editor.card_ids.length }));
}

function cardQuery() {
  const hero = model.editor?.hero;
  const params = new URLSearchParams({
    locale: model.locale,
    scope: "collectible",
    sort: "cost",
    q: model.search,
    page: String(model.cardPage),
    page_size: String(PAGE_SIZE),
  });
  if (model.classScope === "neutral") params.set("class", "NEUTRAL");
  else if (heroClass(hero)) params.set("class", heroClass(hero));
  return `/api/catalog?${params.toString()}`;
}

async function loadCards() {
  const requestId = ++model.cardRequestNumber;
  if (!model.editor?.hero_id) {
    model.cards = [];
    model.totalCards = 0;
    renderCardPicker();
    return;
  }
  refs.cardGrid.setAttribute("aria-busy", "true");
  setStatus(t("loadingCards"));
  try {
    const payload = await request(cardQuery());
    if (requestId !== model.cardRequestNumber) return;
    model.cards = list(payload.items || payload.cards).map(normalizeCard).filter(isDeckCard);
    model.totalCards = Number(payload.total) || model.cards.length;
    model.cardPageSize = Number(payload.page_size) || PAGE_SIZE;
    renderCardPicker();
    setStatus("");
  } catch (error) {
    if (requestId !== model.cardRequestNumber) return;
    model.cards = [];
    model.totalCards = 0;
    renderCardPicker();
    setError(t("requestFailed", { message: error.message || t("network") }));
    setStatus("");
  } finally {
    if (requestId === model.cardRequestNumber) refs.cardGrid.setAttribute("aria-busy", "false");
  }
}

function renderCopy() {
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
  refs.cardSearch.placeholder = model.locale === "enUS" ? "Search card name or ID" : "搜索卡牌名称或 ID";
}

function renderDeckList() {
  refs.deckList.innerHTML = model.decks.map((deck) => {
    const selected = deck.id === model.selectedDeckId;
    const title = deck.name || t("newDeckName");
    const status = deck.complete ? t("complete") : t("incomplete");
    return `<li class="collection-deck-item${selected ? " is-selected" : ""}">
      <button class="collection-deck-select" type="button" data-action="select-deck" data-deck-id="${escapeHtml(deck.id)}" aria-current="${selected ? "true" : "false"}">
        <strong>${escapeHtml(title)}</strong><small>${escapeHtml(String(deck.card_ids.length))} ${escapeHtml(t("cards"))}</small>
      </button><span class="collection-deck-status">${escapeHtml(status)}</span>
    </li>`;
  }).join("");
  refs.deckEmpty.hidden = model.decks.length > 0;
}

function renderHeroGrid() {
  const selectedId = model.editor?.hero_id || "";
  model.heroFaceManager?.release();
  model.heroFaceManager = createStaticCardFaceManager({
    locale: model.locale,
    copy: staticCardFaceCopy(),
  });
  refs.heroGrid.replaceChildren();
  if (!model.heroes.length) {
    refs.heroGrid.append(Object.assign(document.createElement("p"), {
      className: "collection-empty",
      textContent: t("noCards"),
    }));
    return;
  }
  const fragment = document.createDocumentFragment();
  model.heroes.forEach((hero) => {
    const id = cardId(hero);
    const selected = id === selectedId;
    const button = document.createElement("button");
    button.className = `collection-hero-option${selected ? " is-selected" : ""}`;
    button.type = "button";
    button.dataset.action = "choose-hero";
    button.dataset.heroId = id;
    button.setAttribute("aria-pressed", String(selected));
    button.setAttribute("aria-label", `${t("selectHero")}: ${cardName(hero)}`);
    const face = createStaticCardFace(hero, { locale: model.locale, copy: staticCardFaceCopy() });
    button.append(face);
    if (face.dataset.descriptionId) button.setAttribute("aria-describedby", face.dataset.descriptionId);
    const meta = document.createElement("small");
    meta.className = "collection-hero-meta";
    meta.textContent = heroClass(hero) || text(hero?.class, "");
    button.append(meta);
    fragment.append(button);
  });
  refs.heroGrid.append(fragment);
  refs.heroGrid.querySelectorAll(".static-card-face").forEach((face) => {
    const hero = model.heroes.find((item) => cardId(item) === face.dataset.cardId);
    if (hero) model.heroFaceManager.observe(face, hero);
  });
}

function renderCardPicker() {
  const hasHero = Boolean(model.editor?.hero_id);
  refs.cardFilterHint.textContent = hasHero ? `${heroClass(model.editor?.hero) || ""} · ${t("addCards")}` : t("chooseHeroFirst");
  refs.classTabs.forEach((tab) => {
    tab.disabled = !hasHero;
    const selected = tab.dataset.scope === model.classScope;
    tab.classList.toggle("is-selected", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  refs.clearSearch.hidden = !model.search;
  model.cardFaceManager?.release();
  model.cardFaceManager = createStaticCardFaceManager({
    locale: model.locale,
    copy: staticCardFaceCopy(),
  });
  if (!hasHero) {
    refs.cardGrid.replaceChildren(Object.assign(document.createElement("p"), {
      className: "collection-empty",
      textContent: t("chooseHeroFirst"),
    }));
    refs.cardEmpty.hidden = true;
    refs.cardPagination.hidden = true;
    return;
  }
  if (!model.cards.length) {
    refs.cardGrid.replaceChildren();
    refs.cardEmpty.textContent = model.search ? t("noCards") : t("noHeroCards");
    refs.cardEmpty.hidden = false;
  } else {
    refs.cardEmpty.hidden = true;
    refs.cardGrid.replaceChildren();
    const fragment = document.createDocumentFragment();
    model.cards.forEach((card) => {
      const result = canAddCard(card);
      const id = cardId(card);
      const rarity = cardRarity(card);
      const disabled = !result.ok;
      const title = disabled ? `${cardName(card)} · ${result.reason}` : `${t("add")}: ${cardName(card)}`;
      const option = document.createElement("div");
      option.className = "collection-card-option-wrap";
      const button = document.createElement("button");
      button.className = `collection-card-option${disabled ? " is-unavailable" : ""}`;
      button.type = "button";
      button.dataset.action = "add-card";
      button.dataset.cardId = id;
      button.setAttribute("aria-label", title);
      if (disabled) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      }
      const face = createStaticCardFace(card, { locale: model.locale, copy: staticCardFaceCopy() });
      button.append(face);
      if (face.dataset.descriptionId) button.setAttribute("aria-describedby", face.dataset.descriptionId);
      const meta = document.createElement("span");
      meta.className = "collection-card-face-meta";
      meta.textContent = `${id} · ${rarity || "—"}`;
      button.append(meta);
      option.append(button);
      const inspect = document.createElement("button");
      inspect.className = "collection-card-inspect";
      inspect.type = "button";
      inspect.dataset.action = "inspect-card";
      inspect.dataset.cardId = id;
      inspect.dataset.testid = "collection-card-inspect";
      inspect.setAttribute("aria-label", `${t("inspect")}: ${cardName(card)}`);
      inspect.textContent = t("inspect");
      option.append(inspect);
      fragment.append(option);
    });
    refs.cardGrid.append(fragment);
    refs.cardGrid.querySelectorAll(".static-card-face").forEach((face) => {
      const card = model.cards.find((item) => cardId(item) === face.dataset.cardId);
      if (card) model.cardFaceManager.observe(face, card);
    });
  }
  const totalPages = Math.max(1, Math.ceil(model.totalCards / model.cardPageSize));
  refs.cardPagination.hidden = totalPages <= 1;
  refs.cardPageLabel.textContent = t("page", { current: model.cardPage, total: totalPages });
  refs.previousPage.disabled = model.cardPage <= 1;
  refs.nextPage.disabled = model.cardPage >= totalPages;
}

function sortedEditorCards() {
  const copies = new Map();
  model.editor?.card_ids.forEach((id) => copies.set(id, (copies.get(id) || 0) + 1));
  return [...(model.editor?.cards || [])]
    .filter((card) => copies.has(cardId(card)))
    .map((card) => ({ card, copies: copies.get(cardId(card)) }))
    .sort((first, second) => (cardCost(first.card) ?? Infinity) - (cardCost(second.card) ?? Infinity) || cardName(first.card).localeCompare(cardName(second.card), model.locale === "zhCN" ? "zh" : "en"));
}

function renderSelectedCards() {
  const cards = sortedEditorCards();
  const count = model.editor?.card_ids.length || 0;
  refs.cardCount.textContent = `${count} / 30`;
  refs.selectedEmpty.hidden = cards.length > 0;
  refs.selectedList.innerHTML = cards.map(({ card, copies }) => {
    const id = cardId(card);
    const cost = cardCost(card);
    return `<li class="collection-selected-item"><span class="collection-selected-cost">${escapeHtml(cost === null ? "—" : cost)}</span>
      <span class="collection-selected-copy"><strong>${escapeHtml(cardName(card))}${copies > 1 ? ` ×${copies}` : ""}</strong><small>${escapeHtml(id)}</small></span>
      <button class="collection-selected-remove" type="button" data-action="remove-card" data-card-id="${escapeHtml(id)}" aria-label="${escapeHtml(`${t("remove")}: ${cardName(card)}`)}">×</button>
    </li>`;
  }).join("");

  const counts = Array(8).fill(0);
  (model.editor?.cards || []).forEach((card) => {
    const copies = model.editor.card_ids.filter((id) => id === cardId(card)).length;
    const cost = cardCost(card);
    if (cost !== null) counts[Math.min(cost, 7)] += copies;
  });
  const largest = Math.max(1, ...counts);
  refs.manaBars.innerHTML = counts.map((count, index) => {
    const label = index === 7 ? "7+" : String(index);
    const height = Math.round((count / largest) * 100);
    return `<li class="collection-mana-column" data-mana-bucket="${label}" data-count="${count}" aria-label="${escapeHtml(`${label}: ${count}`)}">
      <span class="collection-mana-count">${count}</span><span class="collection-mana-track"><span class="collection-mana-fill" style="height:${height}%"></span></span><span class="collection-mana-label">${label}</span>
    </li>`;
  }).join("");
}

function renderBattleLink() {
  const complete = Boolean(model.editor?.complete && model.editor?.card_ids.length === 30 && !model.dirty);
  refs.battleLink.hidden = !complete || !model.editor?.id;
  if (complete && model.editor?.id) refs.battleLink.href = `/?deck=${encodeURIComponent(model.editor.id)}`;
}

function renderEditor() {
  const hasEditor = Boolean(model.editor);
  refs.editorEmpty.hidden = hasEditor;
  refs.editor.hidden = !hasEditor;
  if (!hasEditor) {
    model.heroFaceManager?.release();
    model.heroFaceManager = null;
    model.cardFaceManager?.release();
    model.cardFaceManager = null;
    refs.heroGrid.replaceChildren();
    refs.cardGrid.replaceChildren();
    return;
  }
  refs.name.value = model.editor.name;
  renderHeroGrid();
  renderCardPicker();
  renderSelectedCards();
  renderBattleLink();
}

function renderAll() {
  closeCardDetail();
  renderCopy();
  renderAccountControls();
  refs.loading.hidden = true;
  refs.layout.hidden = false;
  renderDeckList();
  renderEditor();
}

function handleClick(event) {
  const node = event.target.closest("[data-action]");
  if (!node || (!refs.app.contains(node) && !refs.cardDialog?.contains(node)) || model.busy) return;
  const action = node.dataset.action;
  if (action === "new-deck") return newDeck();
  if (action === "select-deck") return selectDeck(node.dataset.deckId);
  if (action === "choose-hero") return chooseHero(node.dataset.heroId);
  if (action === "inspect-card") return inspectCard(node.dataset.cardId);
  if (action === "close-card-detail") return closeCardDetail();
  if (action === "add-card") {
    const card = model.cards.find((item) => cardId(item) === node.dataset.cardId);
    if (card) addCard(card);
    return;
  }
  if (action === "remove-card") return removeCard(node.dataset.cardId);
  if (action === "delete-deck") return void deleteDeck();
  if (action === "clear-search") {
    refs.cardSearch.value = "";
    model.search = "";
    model.cardPage = 1;
    void loadCards();
    return;
  }
  if (action === "class-scope") {
    model.classScope = node.dataset.scope === "neutral" ? "neutral" : "class";
    model.cardPage = 1;
    renderCardPicker();
    void loadCards();
    return;
  }
  if (action === "previous-page" && model.cardPage > 1) {
    model.cardPage -= 1;
    void loadCards();
    return;
  }
  if (action === "next-page") {
    const pages = Math.max(1, Math.ceil(model.totalCards / model.cardPageSize));
    if (model.cardPage < pages) {
      model.cardPage += 1;
      void loadCards();
    }
  }
}

refs.app.addEventListener("click", handleClick);
refs.cardDialog?.addEventListener("click", handleClick);
refs.cardDialog?.addEventListener("close", clearCardDetail);
refs.editor.addEventListener("submit", (event) => { void saveDeck(event); });
refs.cardSearch.addEventListener("input", () => {
  model.search = refs.cardSearch.value.trim();
  model.cardPage = 1;
  window.clearTimeout(model.cardTimer);
  model.cardTimer = window.setTimeout(() => { void loadCards(); }, 180);
});
refs.name.addEventListener("input", () => {
  if (model.editor) {
    model.editor.name = refs.name.value;
    model.dirty = true;
  }
});

refs.localeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (model.busy || !COPY[button.dataset.locale]) return;
    if (!confirmDiscard()) return;
    model.locale = button.dataset.locale;
    saveLocale(model.locale);
    renderAll();
    void loadDecks(model.selectedDeckId);
  });
});

refs.accountLogout.addEventListener("click", () => { void logoutAccount(); });
refs.accountImport.addEventListener("click", () => { void importLegacy(); });

function confirmDiscard() {
  return !model.dirty || window.confirm(t("discard"));
}

window.addEventListener("beforeunload", (event) => {
  if (!model.dirty) return;
  event.preventDefault();
  event.returnValue = t("unsaved");
});

void (async () => {
  renderCopy();
  renderAccountControls();
  setStatus(t("loading"));
  if (!(await loadAccountSession())) return;
  watchAccountSession(model.account.id, () => {
    model.dirty = false;
    window.location.replace(accountUrl());
  });
  await loadDecks();
  if (model.editor) void loadCards();
})();
