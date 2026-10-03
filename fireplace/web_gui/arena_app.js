import { announceAccountChange, watchAccountSession } from "./account_session.js";

/*
 * Arena composition root.
 *
 * The arena is a small, state-driven flow that deliberately lives outside
 * the match GUI. The server owns the run and its revision; this module only
 * renders the current state and submits one explicit choice at a time.
 */

const MIN_POOL_BUDGET = 14;
const MAX_POOL_BUDGET = 18;
const CUSTOM_FORMAT_ID = "custom_v1";
const HISTORICAL_FORMAT_ID = "wild_2016_09_02";
const HISTORICAL_SET_IDS = ["BASIC", "EXPERT1", "NAXX", "GVG", "BRM", "TGT", "LOE", "OG", "KARA"];
const HISTORICAL_SET_LABELS = {
  BASIC: { zhCN: "基础", enUS: "Basic" },
  EXPERT1: { zhCN: "经典", enUS: "Classic" },
  NAXX: { zhCN: "纳克萨玛斯", enUS: "Naxxramas" },
  GVG: { zhCN: "地精大战侏儒", enUS: "GvG" },
  BRM: { zhCN: "黑石山的火焰", enUS: "Blackrock Mountain" },
  TGT: { zhCN: "冠军的试炼", enUS: "The Grand Tournament" },
  LOE: { zhCN: "探险者协会", enUS: "The League of Explorers" },
  OG: { zhCN: "上古之神的低语", enUS: "Whispers of the Old Gods" },
  KARA: { zhCN: "卡拉赞之夜", enUS: "One Night in Karazhan" },
};
const ARENA_CLASS_LABELS = {
  DRUID: { zhCN: "德鲁伊", enUS: "Druid" },
  HUNTER: { zhCN: "猎人", enUS: "Hunter" },
  MAGE: { zhCN: "法师", enUS: "Mage" },
  PALADIN: { zhCN: "圣骑士", enUS: "Paladin" },
  PRIEST: { zhCN: "牧师", enUS: "Priest" },
  ROGUE: { zhCN: "盗贼", enUS: "Rogue" },
  SHAMAN: { zhCN: "萨满祭司", enUS: "Shaman" },
  WARLOCK: { zhCN: "术士", enUS: "Warlock" },
  WARRIOR: { zhCN: "战士", enUS: "Warrior" },
  DEMONHUNTER: { zhCN: "恶魔猎手", enUS: "Demon Hunter" },
  DEMON_HUNTER: { zhCN: "恶魔猎手", enUS: "Demon Hunter" },
  DEATHKNIGHT: { zhCN: "死亡骑士", enUS: "Death Knight" },
  DEATH_KNIGHT: { zhCN: "死亡骑士", enUS: "Death Knight" },
  NEUTRAL: { zhCN: "中立", enUS: "Neutral" },
};

const COPY = {
  zhCN: {
    back: "返回开始界面",
    history: "对局存档",
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
    setupIntro: "基础和经典卡牌固定在卡池中，不计入扩展包点数。另选扩展包：大包 3 点，小包 1 点。",
    nickname: "竞技场昵称",
    nicknamePlaceholder: "例如：旅店老板",
    nicknameHint: "昵称只保存在这台设备上。",
    format: "竞技场格式",
    formatHint: "开始后本轮竞技场不能更换格式。",
    customFormat: "自定义卡池（当前）",
    historicalFormat: "历史狂野卡池 · 2016-09-02",
    historicalSetupIntro: "固定使用截至 2016-09-02 的历史卡池，不选择扩展包。",
    historicalPoolTitle: "固定历史卡池",
    historicalPoolDescription: "Basic、Classic、Naxxramas、GvG、Blackrock Mountain、The Grand Tournament、The League of Explorers、Whispers of the Old Gods 和 One Night in Karazhan。",
    historicalPoolLabel: "Basic · Classic · Naxxramas · GvG · Blackrock Mountain · The Grand Tournament · The League of Explorers · Whispers of the Old Gods · One Night in Karazhan",
    historicalOfferApprox: "选牌权重为近似值：本次运行使用重建的历史策略。",
    historicalCombatLimit: "对战限制：实际对战使用当前 Fireplace 实现。",
    historicalKnownLimitations: "限制：选牌按历史卡池重建；卡牌效果、发现和随机生成仍使用当前 Fireplace 实现。",
    recordTarget: "目标：{maxWins} 胜或 {maxLosses} 负",
    fixedMcts: "MCTS 策略（固定）",
    fixedMctsDescription: "竞技场对手始终使用 MCTS 搜索策略。",
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
    budgetRule: "总点数允许 14–18 点，大包 3 点，小包 1 点。",
    budgetReady: "卡池选择完成，可以开始选英雄。",
    budgetInvalid: "请选择总计 14–18 点的扩展包。",
    startArena: "开始竞技场",
    starting: "正在创建竞技场……",
    heroTitle: "选择你的英雄",
    heroIntro: "从三个随机英雄中选择一个。之后的三十轮选牌会遵循这个职业和当前卡池。",
    chooseHero: "选择这个英雄",
    draftTitle: "选择一张卡牌",
    draftIntro: "每轮从三张牌中选择一张加入牌组。白板牌也会出现在首版卡池中。",
    draftProgress: "第 {current} / {total} 轮",
    ratingSource: "评分来源：{name} · {asOf} · {cardClass} 当前职业",
    ratingNote: "“*”保留原表标记；显示原始分数，不额外修正，也不按 100 分制归一化。",
    ratingLabel: "评分 {raw}",
    highestRating: "最高分",
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
    retireArena: "退出本轮竞技场",
    retireConfirm: "退出后本轮竞技场将结束，确定退出吗？",
    retiring: "正在结束本轮竞技场……",
    completeTitle: "竞技场结束",
    completeIntro: "本次竞技场已达到 {maxWins} 胜或 {maxLosses} 负。",
    retiredTitle: "本轮竞技场已结束",
    retiredIntro: "你主动结束了本轮竞技场，牌组和当前战绩已保留。",
    finalRecord: "最终战绩",
    startAgain: "重新开始",
    loading: "正在读取竞技场状态……",
    waiting: "正在等待服务器……",
    qualityYellow: "效果待验证",
    qualityRed: "效果存在问题",
    unknownSet: "未标记系列",
    unknownClass: "中立",
    missingArt: "暂无图片",
    requestFailed: "竞技场请求失败：{message}",
    invalidName: "请输入竞技场昵称。",
    invalidBudget: "请选择总计 14–18 点的扩展包。",
    network: "无法连接本机竞技场服务。",
    reset: "返回选包",
    resumeTitle: "有一局未完成对战",
    resumeIntro: "竞技场牌组已经准备好，但当前对战没有在此页面保持活动状态。",
    resumeOpenArchives: "有一局未完成对战，打开存档继续",
  },
  enUS: {
    back: "Back to start",
    history: "Game archives",
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
    setupIntro: "Basic and Classic cards are always in the pool and cost no points. Choose expansions worth 14–18 points: large packs cost 3 and small packs cost 1.",
    nickname: "Arena nickname",
    nicknamePlaceholder: "For example: Innkeeper",
    nicknameHint: "Your nickname stays on this device.",
    format: "Arena format",
    formatHint: "The format cannot change after this run starts.",
    customFormat: "Custom pool (current)",
    historicalFormat: "Historical Wild pool · 2016-09-02",
    historicalSetupIntro: "Use the fixed card pool from 2016-09-02; no expansion selection is needed.",
    historicalPoolTitle: "Fixed historical pool",
    historicalPoolDescription: "Basic, Classic, Naxxramas, GvG, Blackrock Mountain, The Grand Tournament, The League of Explorers, Whispers of the Old Gods, and One Night in Karazhan.",
    historicalPoolLabel: "Basic · Classic · Naxxramas · GvG · Blackrock Mountain · The Grand Tournament · The League of Explorers · Whispers of the Old Gods · One Night in Karazhan",
    historicalOfferApprox: "Offer weights are approximate: this run uses a reconstructed historical policy.",
    historicalCombatLimit: "Combat limitation: battles use the current Fireplace implementation.",
    historicalKnownLimitations: "Known limitation: drafting uses the reconstructed historical pool; card effects, Discover, and random generation use the current Fireplace implementation.",
    recordTarget: "Target: {maxWins} wins or {maxLosses} losses",
    fixedMcts: "MCTS strategy (fixed)",
    fixedMctsDescription: "Arena opponents always use the MCTS search strategy.",
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
    budgetRule: "Choose 14–18 points in total: large packs cost 3 and small packs cost 1.",
    budgetReady: "Pool complete. You can choose your hero.",
    budgetInvalid: "Choose packs worth 14–18 points.",
    startArena: "Start arena",
    starting: "Creating arena run…",
    heroTitle: "Choose your hero",
    heroIntro: "Pick one of three random heroes. The next thirty draft rounds follow this class and pool.",
    chooseHero: "Choose this hero",
    draftTitle: "Choose a card",
    draftIntro: "Pick one of three cards to add to your deck. Blank cards are allowed in the first version.",
    draftProgress: "Round {current} / {total}",
    ratingSource: "Ratings: {name} · {asOf} · {cardClass} current class",
    ratingNote: "“*” is kept as the original table mark; the original score is shown without added modifiers or normalization to a 100-point scale.",
    ratingLabel: "Rating {raw}",
    highestRating: "Highest score",
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
    retireArena: "Retire arena run",
    retireConfirm: "Retiring ends this entire arena run. Retire now?",
    retiring: "Ending arena run…",
    completeTitle: "Arena complete",
    completeIntro: "This arena ended at {maxWins} wins or {maxLosses} losses.",
    retiredTitle: "Arena run ended",
    retiredIntro: "You ended this arena run. Your deck and current record were kept.",
    finalRecord: "Final record",
    startAgain: "Start again",
    loading: "Loading arena state…",
    waiting: "Waiting for the server…",
    qualityYellow: "Effects not fully verified",
    qualityRed: "Known effect issues",
    unknownSet: "Unmarked set",
    unknownClass: "Neutral",
    missingArt: "No image",
    requestFailed: "Arena request failed: {message}",
    invalidName: "Enter an arena nickname.",
    invalidBudget: "Choose 14–18 expansion points.",
    network: "The local arena service is unavailable.",
    reset: "Back to packs",
    resumeTitle: "An unfinished match is waiting",
    resumeIntro: "Your Arena deck is ready, but the active match is no longer open on this page.",
    resumeOpenArchives: "Open archives to continue the unfinished match",
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
  selectedFormatId: CUSTOM_FORMAT_ID,
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

function normalizeFormatId(value) {
  const id = text(value).trim();
  return id === HISTORICAL_FORMAT_ID ? HISTORICAL_FORMAT_ID : CUSTOM_FORMAT_ID;
}

function formatId(state) {
  return normalizeFormatId(state?.format_id);
}

function isHistoricalFormat(state) {
  return formatId(state) === HISTORICAL_FORMAT_ID;
}

function positiveLimit(value, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

function formatOptions(state) {
  const options = list(state?.formats).map((option) => {
    const id = normalizeFormatId(option?.id);
    if (!text(option?.id).trim() || (text(option?.id).trim() !== CUSTOM_FORMAT_ID && text(option?.id).trim() !== HISTORICAL_FORMAT_ID)) return null;
    const fallbackLabel = id === HISTORICAL_FORMAT_ID ? t("historicalFormat") : t("customFormat");
    return {
      id,
      label: text(option?.label).trim() || fallbackLabel,
      max_wins: positiveLimit(option?.max_wins, id === HISTORICAL_FORMAT_ID ? 12 : 7),
      max_losses: positiveLimit(option?.max_losses, 3),
    };
  }).filter(Boolean);
  const unique = [];
  options.forEach((option) => {
    if (!unique.some((candidate) => candidate.id === option.id)) unique.push(option);
  });
  if (!unique.length) {
    unique.push({ id: CUSTOM_FORMAT_ID, label: t("customFormat"), max_wins: 7, max_losses: 3 });
  }
  return unique;
}

function formatOption(state, id) {
  return formatOptions(state).find((option) => option.id === normalizeFormatId(id)) || formatOptions(state)[0];
}

function historicalSetName(setId) {
  return HISTORICAL_SET_LABELS[setId]?.[model.locale] || setId;
}

function knownLimitations(state) {
  const provided = list(state?.known_limitations).map((value) => text(value).trim()).filter(Boolean);
  // The current service keeps these metadata strings language-neutral. Keep
  // the historical notice translated even when a Chinese state contains the
  // English compatibility payload.
  return model.locale === "zhCN" ? [t("historicalKnownLimitations")] : (provided.length ? provided : [t("historicalKnownLimitations")]);
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
  const value = text(card?.class, text(card?.hero_class, text(card?.player_class, t("unknownClass"))));
  const normalized = value.trim().toUpperCase();
  return ARENA_CLASS_LABELS[normalized]?.[model.locale] || value;
}

function cardSet(card) {
  return text(card?.card_set, text(card?.set, t("unknownSet")));
}

function qualityNotice(card) {
  const status = text(card?.quality_status).trim().toUpperCase();
  if (status === "YELLOW") return { status, label: t("qualityYellow") };
  if (status === "RED") return { status, label: t("qualityRed") };
  return null;
}

function historicalRating(card) {
  const source = card?.arena_rating;
  if (!source || typeof source !== "object") return null;
  const rawNumeric = source.numeric;
  if (rawNumeric === null || rawNumeric === undefined || (typeof rawNumeric === "string" && !rawNumeric.trim())) return null;
  if (typeof rawNumeric !== "number" && typeof rawNumeric !== "string") return null;
  const numeric = Number(rawNumeric);
  if (!Number.isFinite(numeric)) return null;
  const raw = text(source.raw).trim() || String(rawNumeric).trim();
  return raw ? { raw, numeric } : null;
}

function highestHistoricalRatingIds(cards) {
  const rated = list(cards).map((card) => ({ id: cardId(card), rating: historicalRating(card) }))
    .filter((entry) => entry.rating);
  if (!rated.length) return new Set();
  const highest = Math.max(...rated.map((entry) => entry.rating.numeric));
  return new Set(rated.filter((entry) => entry.rating.numeric === highest).map((entry) => entry.id));
}

function historicalRatingSource(state, cards) {
  const metadata = state?.rating_source && typeof state.rating_source === "object" ? state.rating_source : {};
  const ratedCard = list(cards).find((card) => historicalRating(card));
  const cardSource = ratedCard?.arena_rating && typeof ratedCard.arena_rating === "object" ? ratedCard.arena_rating : {};
  const hero = state?.hero && typeof state.hero === "object" ? state.hero : {};
  const sourceName = text(metadata.name).trim() || text(cardSource.source).trim() || "Lightforge";
  const asOf = text(metadata.as_of).trim() || text(cardSource.as_of).trim() || "2016-09-02";
  const sourceClass = text(metadata.card_class).trim()
    || text(cardSource.card_class).trim()
    || text(hero.class).trim()
    || text(hero.hero_class).trim()
    || t("unknownClass");
  return { name: sourceName, asOf, cardClass: cardClass({ class: sourceClass }) };
}

function renderHistoricalRatingHeader(state, cards) {
  if (!isHistoricalFormat(state)) return "";
  const source = historicalRatingSource(state, cards);
  return `
    <aside class="arena-rating-header" data-testid="arena-rating-source">
      <strong>${escapeHtml(t("ratingSource", source))}</strong>
      <p>${escapeHtml(t("ratingNote"))}</p>
    </aside>`;
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
  const normalizedFormatId = normalizeFormatId(value.format_id);
  return {
    ...value,
    mode: ["setup", "hero", "draft", "ready", "match", "resume", "complete"].includes(value.mode) ? value.mode : "setup",
    format_id: normalizedFormatId,
    formats: list(value.formats),
    max_wins: positiveLimit(value.max_wins, normalizedFormatId === HISTORICAL_FORMAT_ID ? 12 : 7),
    max_losses: positiveLimit(value.max_losses, 3),
    known_limitations: list(value.known_limitations),
    offer_policy_accuracy: text(value.offer_policy_accuracy).trim().toLowerCase(),
    wins: Number.isFinite(Number(value.wins)) ? Number(value.wins) : 0,
    losses: Number.isFinite(Number(value.losses)) ? Number(value.losses) : 0,
    retired: value.retired === true,
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
  const record = refs.headerWins.closest(".arena-record");
  if (record) {
    record.setAttribute("aria-label", t("recordTarget", {
      maxWins: positiveLimit(state.max_wins, 7),
      maxLosses: positiveLimit(state.max_losses, 3),
    }));
  }
}

function updateProgress() {
  const order = ["setup", "hero", "draft", "ready"];
  const mode = currentMode();
  const index = mode === "complete" || mode === "resume" ? order.length : Math.max(0, order.indexOf(mode));
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
    const budgetInvalid = button.dataset.action === "start"
      && setupFormatId(model.state) !== HISTORICAL_FORMAT_ID
      && !isBudgetValid(model.state);
    button.disabled = model.busy || budgetInvalid || button.dataset.alwaysEnabled === "true";
  });
  refs.stage?.querySelectorAll("select[data-format-select]").forEach((select) => {
    select.disabled = model.busy || currentMode() !== "setup";
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
  model.selectedFormatId = formatId(next);
  if (next.mode === "setup" && isHistoricalFormat(next)) {
    model.selectedPacks.clear();
  } else if (next.mode === "setup" && Array.isArray(next.selected_sets)) {
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
  else if (state.mode === "resume") refs.stage.innerHTML = renderResumeStage(state);
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

function isBudgetValid(state) {
  const budget = selectedBudget(state);
  return budget >= MIN_POOL_BUDGET && budget <= MAX_POOL_BUDGET;
}

function setupFormatId(state) {
  const selected = normalizeFormatId(model.selectedFormatId);
  return formatOptions(state).some((option) => option.id === selected) ? selected : formatId(state);
}

function formatTarget(state, id = formatId(state)) {
  const option = formatOption(state, id);
  const useStateLimits = formatId(state) === normalizeFormatId(id);
  return {
    maxWins: useStateLimits ? positiveLimit(state?.max_wins, positiveLimit(option?.max_wins, 7)) : positiveLimit(option?.max_wins, 7),
    maxLosses: useStateLimits ? positiveLimit(state?.max_losses, positiveLimit(option?.max_losses, 3)) : positiveLimit(option?.max_losses, 3),
  };
}

function renderFormatSelector(state) {
  if (formatOptions(state).length < 2) return "";
  const selectedId = setupFormatId(state);
  const options = formatOptions(state).map((option) => `
      <option value="${escapeHtml(option.id)}" ${option.id === selectedId ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("");
  return `
    <div class="arena-field arena-format-field" data-testid="arena-format-field">
      <label for="arena-format">${escapeHtml(t("format"))}</label>
      <select id="arena-format" data-testid="arena-format" data-format-select aria-describedby="arena-format-hint">${options}</select>
      <small id="arena-format-hint">${escapeHtml(t("formatHint"))}</small>
    </div>`;
}

function renderHistoricalPool(state) {
  const target = formatTarget(state, HISTORICAL_FORMAT_ID);
  const sets = HISTORICAL_SET_IDS.map((setId) => `<span data-set-id="${escapeHtml(setId)}">${escapeHtml(historicalSetName(setId))}</span>`).join("");
  return `
    <section class="arena-historical-pool" data-testid="arena-historical-pool" aria-labelledby="arena-historical-pool-title">
      <div class="arena-group-heading"><h3 id="arena-historical-pool-title">${escapeHtml(t("historicalPoolTitle"))}</h3><span>${escapeHtml(t("recordTarget", target))}</span></div>
      <p>${escapeHtml(t("historicalPoolDescription"))}</p>
      <div class="arena-historical-set-list" aria-label="${escapeHtml(t("historicalPoolTitle"))}">${sets}</div>
    </section>`;
}

function renderFormatNotice(state) {
  if (!isHistoricalFormat(state)) return "";
  const target = formatTarget(state, HISTORICAL_FORMAT_ID);
  const limitations = knownLimitations(state).map((value) => `<li>${escapeHtml(value)}</li>`).join("");
  const approximate = state.offer_policy_accuracy === "reconstructed"
    ? `<p class="arena-format-notice-warning" data-testid="arena-offer-policy-notice">${escapeHtml(t("historicalOfferApprox"))}</p>`
    : "";
  return `
    <aside class="arena-format-notice" data-testid="arena-format-notice">
      <div class="arena-format-notice-heading"><strong>${escapeHtml(t("historicalFormat"))}</strong><span>${escapeHtml(t("recordTarget", target))}</span></div>
      <ul>${limitations}</ul>
      ${approximate}
      <p class="arena-format-notice-warning" data-testid="arena-combat-limitation">${escapeHtml(t("historicalCombatLimit"))}</p>
    </aside>`;
}

function renderSetup(state) {
  const selectedId = setupFormatId(state);
  const historical = selectedId === HISTORICAL_FORMAT_ID;
  const budget = selectedBudget(state);
  const ready = historical || isBudgetValid(state);
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
        ${renderFormatSelector(state)}
        ${historical ? `<p class="arena-lead arena-format-intro">${escapeHtml(t("historicalSetupIntro"))}</p>${renderHistoricalPool(state)}${renderFormatNotice({ ...state, format_id: HISTORICAL_FORMAT_ID, max_wins: undefined, max_losses: undefined, offer_policy_accuracy: "reconstructed" })}` : `
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
        `}
      </section>
      <aside class="arena-panel arena-budget-panel" aria-labelledby="arena-budget-title">
        <div class="arena-budget-ring${ready ? " is-ready" : ""}" aria-label="${escapeHtml(historical ? t("recordTarget", formatTarget(state, HISTORICAL_FORMAT_ID)) : `${t("budget")}: ${budget}; ${MIN_POOL_BUDGET}–${MAX_POOL_BUDGET}`)}">
          ${historical ? `<strong>${escapeHtml(String(formatTarget(state, HISTORICAL_FORMAT_ID).maxWins))}</strong><span>${escapeHtml(t("wins"))}</span>` : `<strong>${budget}</strong><span>${MIN_POOL_BUDGET}–${MAX_POOL_BUDGET} ${escapeHtml(t("points"))}</span>`}
        </div>
        <p class="eyebrow">ARENA POOL</p>
        <h2 id="arena-budget-title">${escapeHtml(historical ? t("historicalPoolTitle") : t("budget"))}</h2>
        <p class="arena-budget-copy">${escapeHtml(historical ? t("recordTarget", formatTarget(state, HISTORICAL_FORMAT_ID)) : (ready ? t("budgetReady") : t("budgetInvalid")))}</p>
        ${historical ? "" : `<p class="arena-selected-count"><span>${escapeHtml(t("selectedPacks"))}</span><strong>${model.selectedPacks.size}</strong></p>`}
        <button class="primary-button arena-action-button" type="button" data-action="start" data-testid="arena-start" ${ready ? "" : "disabled"}>${escapeHtml(t("startArena"))}</button>
      </aside>
    </div>`;
}

function renderChoiceCard(card, kind, context = {}) {
  const id = cardId(card);
  const name = cardName(card);
  const textValue = text(card?.text, t("noText"));
  const cost = card?.cost === undefined ? "" : `<span class="arena-card-cost">${escapeHtml(numberOrDash(card.cost))}</span>`;
  const stats = [
    card?.attack === undefined ? "" : `<span>${escapeHtml(t("attack"))} ${escapeHtml(numberOrDash(card.attack))}</span>`,
    card?.health === undefined ? "" : `<span>${escapeHtml(t("health"))} ${escapeHtml(numberOrDash(card.health))}</span>`,
  ].filter(Boolean).join("");
  const quality = qualityNotice(card);
  const rating = kind === "card" && context.showRating === true ? historicalRating(card) : null;
  const highest = Boolean(rating && context.bestIds instanceof Set && context.bestIds.has(id));
  const ratingLabel = rating ? [
    t("ratingLabel", { raw: rating.raw }),
    highest ? t("highestRating") : "",
  ].filter(Boolean).join(" · ") : "";
  const accessibleName = [name, ratingLabel].filter(Boolean).join(" — ");
  return `
    <article class="arena-choice-card" data-card-id="${escapeHtml(id)}">
      <button class="arena-choice-button" type="button" data-action="${kind === "hero" ? "choose-hero" : "pick-card"}" data-choice-id="${escapeHtml(id)}" aria-label="${escapeHtml(accessibleName)}">
        <div class="arena-choice-art-wrap">${cardArt(card, name)}${cost}</div>
        <div class="arena-choice-copy">
          <div class="arena-choice-title"><h3>${escapeHtml(name)}</h3>${stats ? `<span class="arena-card-stats">${stats}</span>` : ""}</div>
          <p class="arena-card-meta"><span>${escapeHtml(cardClass(card))}</span><span>${escapeHtml(cardSet(card))}</span></p>
          <p class="arena-card-text">${escapeHtml(textValue)}</p>
          ${rating ? `<div class="arena-rating-row" data-testid="arena-rating" data-rating-numeric="${escapeHtml(String(rating.numeric))}"><span class="arena-rating-badge">${escapeHtml(t("ratingLabel", { raw: rating.raw }))}</span>${highest ? `<span class="arena-rating-highest">${escapeHtml(t("highestRating"))}</span>` : ""}</div>` : ""}
          ${kind === "card" && quality ? `<span class="arena-quality-badge is-quality-${quality.status.toLowerCase()}">${escapeHtml(quality.label)}</span>` : ""}
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
        ${renderFormatNotice(state)}
        <div class="arena-offer-grid arena-hero-offers" data-testid="arena-hero-offer">${offers || `<p class="arena-empty-copy">${escapeHtml(t("waiting"))}</p>`}</div>
      </section>
      <aside class="arena-panel arena-side-panel"><p class="eyebrow">ARENA POOL</p><h2>${escapeHtml(t("selectedPacks"))}</h2>${renderSelectedPacks(state)}${heroSummary(state.hero)}</aside>
    </div>`;
}

function renderSelectedPacks(state) {
  if (isHistoricalFormat(state)) {
    return `<div class="arena-selected-packs arena-historical-selected-packs">${HISTORICAL_SET_IDS.map((setId) => `<span class="arena-basic-chip" data-set-id="${escapeHtml(setId)}">${escapeHtml(historicalSetName(setId))}</span>`).join("")}</div>`;
  }
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
  const cards = list(state.card_offer);
  const historical = isHistoricalFormat(state);
  const bestIds = historical ? highestHistoricalRatingIds(cards) : new Set();
  const offers = cards.map((card) => renderChoiceCard(card, "card", { bestIds, showRating: historical })).join("");
  return `
    <div class="arena-layout arena-draft-layout">
      <section class="arena-panel arena-flow-panel" aria-labelledby="arena-draft-title">
        <div class="arena-panel-heading"><div><p class="eyebrow">CARD DRAFT</p><h2 id="arena-draft-title">${escapeHtml(t("draftTitle"))}</h2></div><span class="arena-panel-number">03</span></div>
        <p class="arena-lead">${escapeHtml(t("draftIntro"))}</p>
        ${renderHistoricalRatingHeader(state, cards)}
        ${renderFormatNotice(state)}
        <p class="arena-draft-progress" data-testid="arena-draft-count">${escapeHtml(t("draftProgress", { current: deck.length + 1, total: 30 }))}</p>
        <div class="arena-offer-grid arena-card-offers" data-testid="arena-card-offer">${offers || `<p class="arena-empty-copy">${escapeHtml(t("waiting"))}</p>`}</div>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function renderFixedMcts() {
  return `
    <div class="arena-basic-lock arena-fixed-opponent" data-testid="arena-fixed-opponent">
      <span class="arena-basic-seal" aria-hidden="true">M</span>
      <span><strong>${escapeHtml(t("fixedMcts"))}</strong><small>${escapeHtml(t("fixedMctsDescription"))}</small></span>
      <span class="arena-lock-icon" aria-hidden="true">◆</span>
    </div>`;
}

function renderReadyStage(state) {
  return `
    <div class="arena-layout arena-ready-layout">
      <section class="arena-panel arena-ready-panel" aria-labelledby="arena-ready-title">
        <div class="arena-panel-heading"><div><p class="eyebrow">DECK COMPLETE</p><h2 id="arena-ready-title">${escapeHtml(t("readyTitle"))}</h2></div><span class="arena-panel-number">04</span></div>
        <p class="arena-lead">${escapeHtml(t("readyIntro"))}</p>
        ${renderFormatNotice(state)}
        ${heroSummary(state.hero)}
        <div class="arena-ready-record"><span>${escapeHtml(t("wins"))}</span><strong>${escapeHtml(text(state.wins, "0"))}</strong><span>${escapeHtml(t("losses"))}</span><strong>${escapeHtml(text(state.losses, "0"))}</strong></div>
        <p class="arena-record-target" data-testid="arena-record-target">${escapeHtml(t("recordTarget", formatTarget(state)))}</p>
        ${renderFixedMcts()}
        <button class="primary-button arena-action-button" type="button" data-action="battle" data-testid="arena-battle">${escapeHtml(t("enterBattle"))}</button>
        <button class="secondary-button arena-action-button arena-retire-button" type="button" data-action="retire" data-testid="arena-retire">${escapeHtml(t("retireArena"))}</button>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function renderCompleteStage(state) {
  const title = state.retired ? t("retiredTitle") : t("completeTitle");
  const intro = state.retired ? t("retiredIntro") : t("completeIntro", formatTarget(state));
  return `
    <div class="arena-layout arena-complete-layout">
      <section class="arena-panel arena-complete-panel" aria-labelledby="arena-complete-title">
        <span class="arena-complete-sigil" aria-hidden="true">✦</span>
        <p class="eyebrow">ARENA RUN COMPLETE</p>
        <h2 id="arena-complete-title">${escapeHtml(title)}</h2>
        <p class="arena-lead">${escapeHtml(intro)}</p>
        ${renderFormatNotice(state)}
        <div class="arena-final-record"><span>${escapeHtml(t("wins"))}</span><strong>${escapeHtml(text(state.wins, "0"))}</strong><i>/</i><strong>${escapeHtml(text(state.losses, "0"))}</strong><span>${escapeHtml(t("losses"))}</span></div>
        <p class="arena-record-target" data-testid="arena-record-target">${escapeHtml(t("recordTarget", formatTarget(state)))}</p>
        <button class="primary-button arena-action-button" type="button" data-action="reset" data-testid="arena-reset">${escapeHtml(t("startAgain"))}</button>
      </section>
      ${renderDeck(state)}
    </div>`;
}

function renderResumeStage(state) {
  const gameId = text(state.resume_game_id).trim();
  const query = gameId ? `?game_id=${encodeURIComponent(gameId)}` : "";
  return `
    <div class="arena-layout arena-complete-layout">
      <section class="arena-panel arena-complete-panel" aria-labelledby="arena-resume-title" data-testid="arena-resume">
        <span class="arena-complete-sigil" aria-hidden="true">↻</span>
        <p class="eyebrow">UNFINISHED MATCH</p>
        <h2 id="arena-resume-title">${escapeHtml(t("resumeTitle"))}</h2>
        <p class="arena-lead">${escapeHtml(t("resumeIntro"))}</p>
        ${renderFormatNotice(state)}
        <a class="primary-button arena-action-button" href="/history${query}" data-testid="arena-resume-link">${escapeHtml(t("resumeOpenArchives"))}</a>
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
    const selectedFormat = setupFormatId(model.state);
    if (selectedFormat !== HISTORICAL_FORMAT_ID && !isBudgetValid(model.state)) {
      setError(t("invalidBudget"));
      return;
    }
    await post("/api/arena/start", {
      nickname,
      locale: model.locale,
      format_id: selectedFormat,
      set_ids: selectedFormat === CUSTOM_FORMAT_ID ? [...model.selectedPacks] : [],
    }, t("starting"));
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
  if (action === "retire") {
    if (!window.confirm(t("retireConfirm"))) return;
    await post("/api/arena/retire", runBody(), t("retiring"));
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

refs.stage.addEventListener("change", (event) => {
  if (event.target?.id !== "arena-format" || model.busy || currentMode() !== "setup") return;
  const selected = text(event.target.value).trim();
  const available = formatOptions(model.state).some((option) => option.id === selected);
  model.selectedFormatId = available ? selected : CUSTOM_FORMAT_ID;
  render();
});

refs.localeButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    if (model.busy || !COPY[button.dataset.locale] || (model.state && currentMode() !== "setup")) return;
    const previousPacks = new Set(model.selectedPacks);
    const previousFormat = model.selectedFormatId;
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
        model.selectedFormatId = previousFormat;
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
