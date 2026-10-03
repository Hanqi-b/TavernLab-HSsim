import { announceAccountChange, watchAccountSession } from "./account_session.js";

/*
 * Match archives are deliberately a small, privacy-aware client.  The API
 * owns the archive and returns only safe summary/public-event projections;
 * this page never asks for or renders a private game checkpoint.
 */

const COPY = {
  zhCN: {
    back: "返回开始界面",
    title: "对局存档",
    subtitle: "查看已保存的对战、继续未完成的对局，或下载结束对局。",
    language: "界面语言",
    navAria: "页面导航",
    paginationAria: "对局存档分页",
    arena: "竞技场",
    lobby: "对战大厅",
    overview: "对局概览",
    refresh: "刷新",
    metricTotal: "全部对局",
    metricActive: "本页未完成",
    metricComplete: "本页已结束",
    listTitle: "你的对局",
    emptyTitle: "还没有对局存档",
    emptyIntro: "开始一局对战后，结束或中断的进度会自动出现在这里。",
    startMatch: "开始对战",
    previous: "上一页",
    next: "下一页",
    detailEyebrow: "对战记录",
    detailTitle: "对战记录",
    closeDetail: "收起记录",
    footer: "查看当前账号保存的对局记录。",
    loading: "正在读取对局存档……",
    loadingDetail: "正在读取对战记录……",
    noEvents: "这局还没有可显示的公开事件。",
    listRange: "第 {start}–{end} 局，共 {total} 局",
    page: "第 {current} / {total} 页",
    fieldYou: "我方",
    fieldOpponent: "对手",
    fieldMode: "模式",
    fieldTime: "开始时间",
    fieldTurn: "回合",
    fieldActions: "操作数",
    fieldResult: "结果",
    unknown: "未知",
    unknownTime: "时间未知",
    modeNormal: "普通对战",
    modeArena: "竞技场",
    statusInProgress: "进行中",
    statusComplete: "已结束",
    statusAbandoned: "已放弃",
    resultActive: "尚未结束",
    resultWin: "获胜",
    resultLoss: "失败",
    resultDraw: "平局",
    resultAbandoned: "已放弃",
    continueMatch: "继续对战",
    download: "下载 JSON",
    viewRecords: "查看记录",
    abandon: "放弃并保留存档",
    abandonTitle: "放弃这局未完成对战？",
    abandonDescription: "放弃后，这局会保留在存档中并标记为已放弃。",
    abandonArenaWarning: "放弃后，这局会保留在存档中并标记为已放弃，同时竞技场记为一次失败。",
    cancel: "继续保留",
    abandonConfirm: "确认放弃",
    abandonDone: "对局已标记为放弃，存档仍然保留。",
    resumeFailed: "无法继续这局对战：{message}",
    abandonFailed: "无法放弃这局对战：{message}",
    detailFailed: "无法读取对战记录：{message}",
    requestFailed: "无法读取对局存档：{message}",
    network: "无法连接本机对局服务。",
    eventChoose: "{actor}完成选择",
    eventPlay: "{actor}打出{source}",
    eventAttack: "{actor}用{source}攻击{target}",
    eventPower: "{actor}使用英雄技能",
    eventMulligan: "{actor}完成换牌",
    eventEndTurn: "{actor}结束回合",
    eventConcede: "{actor}投降",
    eventUnknown: "发生了一个公开事件",
    actorYou: "你",
    actorOpponent: "对手",
    targetUnknown: "目标",
  },
  enUS: {
    back: "Back to start",
    title: "Game archives",
    subtitle: "Review saved matches, continue unfinished games, or download ended games.",
    language: "Language",
    navAria: "Page navigation",
    paginationAria: "Match archive pagination",
    arena: "Arena",
    lobby: "Battle lobby",
    overview: "Match overview",
    refresh: "Refresh",
    metricTotal: "All matches",
    metricActive: "Unfinished on this page",
    metricComplete: "Ended on this page",
    listTitle: "Your matches",
    emptyTitle: "No match archives yet",
    emptyIntro: "Finished and interrupted games will appear here after you start a match.",
    startMatch: "Start a match",
    previous: "Previous",
    next: "Next",
    detailEyebrow: "MATCH RECORD",
    detailTitle: "Match record",
    closeDetail: "Hide record",
    footer: "Matches saved for this account.",
    loading: "Loading match archives…",
    loadingDetail: "Loading match record…",
    noEvents: "There are no public events to show for this match yet.",
    listRange: "Matches {start}–{end} of {total}",
    page: "Page {current} / {total}",
    fieldYou: "You",
    fieldOpponent: "Opponent",
    fieldMode: "Mode",
    fieldTime: "Started",
    fieldTurn: "Turn",
    fieldActions: "Actions",
    fieldResult: "Result",
    unknown: "Unknown",
    unknownTime: "Time unavailable",
    modeNormal: "Normal",
    modeArena: "Arena",
    statusInProgress: "In progress",
    statusComplete: "Complete",
    statusAbandoned: "Abandoned",
    resultActive: "Unfinished",
    resultWin: "Won",
    resultLoss: "Lost",
    resultDraw: "Draw",
    resultAbandoned: "Abandoned",
    continueMatch: "Continue match",
    download: "Download JSON",
    viewRecords: "View records",
    abandon: "Abandon and keep archive",
    abandonTitle: "Abandon this unfinished match?",
    abandonDescription: "The match will stay in your archive and be marked abandoned.",
    abandonArenaWarning: "The match will stay in your archive and be marked abandoned. Arena will also count one loss.",
    cancel: "Keep match",
    abandonConfirm: "Confirm abandon",
    abandonDone: "The match was marked abandoned and kept in your archive.",
    resumeFailed: "Unable to continue this match: {message}",
    abandonFailed: "Unable to abandon this match: {message}",
    detailFailed: "Unable to read the match record: {message}",
    requestFailed: "Unable to read match archives: {message}",
    network: "The local match service is unavailable.",
    eventChoose: "{actor} completed a choice",
    eventPlay: "{actor} played {source}",
    eventAttack: "{actor} attacked {target} with {source}",
    eventPower: "{actor} used a hero power",
    eventMulligan: "{actor} completed a mulligan",
    eventEndTurn: "{actor} ended the turn",
    eventConcede: "{actor} conceded",
    eventUnknown: "A public event occurred",
    actorYou: "You",
    actorOpponent: "Opponent",
    targetUnknown: "a target",
  },
};

const refs = {
  status: document.getElementById("history-status"),
  error: document.getElementById("history-error"),
  metrics: document.getElementById("history-metrics"),
  total: document.getElementById("history-total"),
  active: document.getElementById("history-active"),
  complete: document.getElementById("history-complete"),
  resultCount: document.getElementById("history-result-count"),
  list: document.getElementById("history-list"),
  empty: document.getElementById("history-empty"),
  pagination: document.getElementById("history-pagination"),
  previous: document.getElementById("history-prev"),
  next: document.getElementById("history-next"),
  page: document.getElementById("history-page"),
  detail: document.getElementById("history-detail"),
  detailTitle: document.getElementById("history-detail-title"),
  detailSummary: document.getElementById("history-detail-summary"),
  detailStatus: document.getElementById("history-detail-status"),
  detailEvents: document.getElementById("history-event-list"),
  detailClose: document.getElementById("history-detail-close"),
  refresh: document.getElementById("history-refresh"),
  accountToolbar: document.getElementById("history-account-toolbar"),
  accountLabel: document.getElementById("history-account-label"),
  accountLogout: document.getElementById("history-account-logout"),
  localeButtons: [...document.querySelectorAll("[data-locale]")],
  copyNodes: [...document.querySelectorAll("[data-copy]")],
  nav: document.getElementById("history-nav"),
  paginationNav: document.getElementById("history-pagination"),
  confirmShell: document.getElementById("history-confirm-shell"),
  confirmDescription: document.getElementById("history-confirm-description"),
  confirmCancel: document.getElementById("history-confirm-cancel"),
  confirmSubmit: document.getElementById("history-confirm-submit"),
};

const model = {
  locale: readLocale(),
  account: null,
  matches: [],
  offset: 0,
  limit: 20,
  total: 0,
  busy: false,
  listGeneration: 0,
  detailGeneration: 0,
  detailMatch: null,
  detailEvents: [],
  confirmMatch: null,
  confirmPreviousFocus: null,
  redirecting: false,
};

function text(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function t(key, variables = {}) {
  const value = COPY[model.locale]?.[key] ?? COPY.zhCN[key] ?? key;
  return String(value).replace(/\{(\w+)\}/g, (_match, name) => String(variables[name] ?? ""));
}

function readLocale() {
  try {
    return localStorage.getItem("fireplace.locale") === "enUS" ? "enUS" : "zhCN";
  } catch (_error) {
    return "zhCN";
  }
}

function storeLocale(locale) {
  try { localStorage.setItem("fireplace.locale", locale); } catch (_error) { /* private mode */ }
}

function currentPath() {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") ? path : "/history";
}

function accountUrl() {
  return `/account?next=${encodeURIComponent(currentPath())}`;
}

function accountFromPayload(payload) {
  const account = payload?.account;
  if (!payload?.authenticated || !account || typeof account !== "object") return null;
  const id = text(account.id).trim();
  const username = text(account.username).trim();
  return id && username ? { id, username } : null;
}

function errorMessage(error, fallback = t("network")) {
  return text(error?.message, fallback) || fallback;
}

function redirectToAccount() {
  if (model.redirecting) return;
  model.redirecting = true;
  window.location.replace(accountUrl());
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
    const rawError = payload?.error;
    const message = rawError && typeof rawError === "object"
      ? rawError.message
      : rawError || payload?.message || `${response.status}`;
    const error = new Error(text(message, `${response.status}`));
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function normalizeMatch(value) {
  const source = value && typeof value === "object" ? value : {};
  const mode = source.mode === "arena" ? "arena" : "normal";
  const status = ["in_progress", "complete", "abandoned"].includes(source.status)
    ? source.status
    : "in_progress";
  return {
    gameId: text(source.game_id).trim(),
    revision: number(source.revision, 0),
    mode,
    status,
    startedAt: source.started_at,
    finishedAt: source.finished_at,
    turn: number(source.turn, 0),
    actionCount: number(source.action_count, 0),
    humanName: text(source.human_name, t("fieldYou")),
    opponentName: text(source.opponent_name, t("unknown")),
    humanHero: text(source.human_hero, t("unknown")),
    opponentHero: text(source.opponent_hero, t("unknown")),
    humanWon: source.human_won === true ? true : source.human_won === false ? false : null,
    resumable: source.resumable === true,
    downloadable: source.downloadable === true,
  };
}

function statusLabel(match) {
  return t(match.status === "in_progress" ? "statusInProgress" : match.status === "complete" ? "statusComplete" : "statusAbandoned");
}

function statusClass(match) {
  return match.status.replace("_", "-");
}

function modeLabel(mode) {
  return t(mode === "arena" ? "modeArena" : "modeNormal");
}

function result(match) {
  if (match.status === "in_progress") return { label: t("resultActive"), className: "active" };
  if (match.status === "abandoned") return { label: t("resultAbandoned"), className: "abandoned" };
  if (match.humanWon === true) return { label: t("resultWin"), className: "win" };
  if (match.humanWon === false) return { label: t("resultLoss"), className: "loss" };
  return { label: t("resultDraw"), className: "draw" };
}

function formatDate(value) {
  if (value === null || value === undefined || value === "") return t("unknownTime");
  let date;
  if (typeof value === "number" || /^\d+(?:\.\d+)?$/.test(String(value))) {
    const numeric = Number(value);
    date = new Date(numeric < 100000000000 ? numeric * 1000 : numeric);
  } else {
    date = new Date(String(value));
  }
  if (Number.isNaN(date.getTime())) return t("unknownTime");
  try {
    return new Intl.DateTimeFormat(model.locale === "enUS" ? "en-US" : "zh-CN", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  } catch (_error) {
    return date.toLocaleString();
  }
}

function appendText(node, value) {
  node.appendChild(document.createTextNode(text(value)));
}

function element(tag, className = "", value = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== null) appendText(node, value);
  return node;
}

function field(label, value, className = "") {
  const wrapper = element("div", "history-field");
  const term = element("dt", "", label);
  const description = element("dd", className, value);
  wrapper.append(term, description);
  return wrapper;
}

function actionButton(label, action, match, className) {
  const button = element("button", className, label);
  button.type = "button";
  button.dataset.action = action;
  button.dataset.gameId = match.gameId;
  button.dataset.revision = String(match.revision);
  return button;
}

function matchCard(match) {
  const article = element("article", `history-match-card is-${statusClass(match)}`);
  article.dataset.testid = "history-match-card";
  article.dataset.gameId = match.gameId;

  const top = element("div", "history-match-top");
  const title = element("h3", "history-match-title");
  appendText(title, match.humanHero || match.humanName);
  title.append(element("span", "history-match-vs", "VS"));
  appendText(title, match.opponentHero || match.opponentName);
  const badge = element("span", `history-match-status is-${statusClass(match)}`, statusLabel(match));
  top.append(title, badge);

  const meta = element("div", "history-match-meta");
  meta.append(
    element("span", "", modeLabel(match.mode)),
    element("span", "", formatDate(match.finishedAt || match.startedAt)),
  );

  const fields = element("dl", "history-fields");
  const outcome = result(match);
  fields.append(
    field(t("fieldYou"), `${match.humanName} · ${match.humanHero}`),
    field(t("fieldOpponent"), `${match.opponentName} · ${match.opponentHero}`),
    field(t("fieldMode"), modeLabel(match.mode)),
    field(t("fieldTime"), formatDate(match.startedAt)),
    field(t("fieldTurn"), match.turn),
    field(t("fieldActions"), match.actionCount),
    field(t("fieldResult"), outcome.label, `is-result-${outcome.className}`),
  );

  const actions = element("div", "history-match-actions");
  if (match.status === "in_progress" && match.resumable) {
    actions.append(actionButton(t("continueMatch"), "resume", match, "primary-button history-continue-button"));
  }
  if (match.downloadable && match.status !== "in_progress") {
    const link = element("a", "history-download-button", t("download"));
    link.href = `/api/matches/download?game_id=${encodeURIComponent(match.gameId)}`;
    link.download = `match-${match.gameId.replace(/[^a-zA-Z0-9_-]/g, "_") || "archive"}.json`;
    link.dataset.testid = "history-download";
    actions.append(link);
  }
  actions.append(actionButton(t("viewRecords"), "detail", match, "history-view-button"));
  if (match.status === "in_progress") {
    actions.append(actionButton(t("abandon"), "abandon", match, "danger-button history-abandon-button"));
  }

  article.append(top, meta, fields, actions);
  return article;
}

function setStatus(message = "") {
  refs.status.textContent = message;
}

function setError(message = "") {
  refs.error.textContent = message;
  refs.error.hidden = !message;
}

function renderAccountControls() {
  const authenticated = Boolean(model.account);
  refs.accountToolbar.hidden = !authenticated;
  refs.accountLabel.textContent = authenticated ? model.account.username : "";
  refs.accountLabel.href = "/account";
  refs.accountLabel.setAttribute("aria-label", authenticated ? `${t("title")}: ${model.account.username}` : "");
  refs.accountLogout.textContent = model.locale === "enUS" ? "Log out" : "退出登录";
  refs.accountLogout.disabled = model.busy;
}

function setBusy(value) {
  model.busy = Boolean(value);
  document.querySelectorAll("[data-action]").forEach((node) => {
    if (node instanceof HTMLButtonElement) node.disabled = model.busy;
  });
  refs.refresh.disabled = model.busy;
  refs.previous.disabled = model.busy;
  refs.next.disabled = model.busy;
  refs.detailClose.disabled = model.busy;
  refs.confirmCancel.disabled = model.busy;
  refs.confirmSubmit.disabled = model.busy;
  refs.localeButtons.forEach((button) => { button.disabled = model.busy; });
  renderAccountControls();
}

function renderStaticCopy() {
  refs.copyNodes.forEach((node) => { node.textContent = t(node.dataset.copy); });
  document.documentElement.lang = model.locale === "enUS" ? "en" : "zh-CN";
  document.title = `Fireplace · ${t("title")}`;
  refs.localeButtons.forEach((button) => {
    const selected = button.dataset.locale === model.locale;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  refs.nav.setAttribute("aria-label", t("navAria"));
  refs.paginationNav.setAttribute("aria-label", t("paginationAria"));
  renderAccountControls();
}

function renderMetrics() {
  const active = model.matches.filter((match) => match.status === "in_progress").length;
  const complete = model.matches.filter((match) => match.status !== "in_progress").length;
  refs.total.textContent = String(model.total);
  refs.active.textContent = String(active);
  refs.complete.textContent = String(complete);
}

function renderPagination() {
  const totalPages = Math.max(1, Math.ceil(model.total / model.limit));
  const currentPage = Math.floor(model.offset / model.limit) + 1;
  refs.pagination.hidden = model.total <= model.limit;
  refs.previous.disabled = model.busy || model.offset <= 0;
  refs.next.disabled = model.busy || currentPage >= totalPages;
  refs.page.textContent = t("page", { current: currentPage, total: totalPages });
}

function renderMatches() {
  refs.list.replaceChildren();
  model.matches.forEach((match) => refs.list.append(matchCard(match)));
  const hasMatches = model.matches.length > 0;
  refs.list.hidden = !hasMatches;
  refs.empty.hidden = model.total !== 0;
  const start = model.total === 0 ? 0 : model.offset + 1;
  const end = model.offset + model.matches.length;
  refs.resultCount.textContent = model.total ? t("listRange", { start, end, total: model.total }) : "";
  renderMetrics();
  renderPagination();
}

function detailSummary(match) {
  return `${match.humanHero || match.humanName} · ${modeLabel(match.mode)} · ${formatDate(match.finishedAt || match.startedAt)}`;
}

function actorLabel(event) {
  return event.actor === "self" ? t("actorYou") : event.actor === "opponent" ? t("actorOpponent") : t("unknown");
}

function eventText(event) {
  if (!event || typeof event !== "object") return t("eventUnknown");
  const actor = actorLabel(event);
  const source = text(event.source_name).trim();
  const target = text(event.target_name).trim() || t("targetUnknown");
  switch (text(event.type).toUpperCase()) {
    case "CHOOSE": return t("eventChoose", { actor });
    case "PLAY_CARD": return t("eventPlay", { actor, source: source || t("unknown") });
    case "ATTACK": return t("eventAttack", { actor, source: source || t("unknown"), target });
    case "USE_HERO_POWER": return t("eventPower", { actor });
    case "MULLIGAN": return t("eventMulligan", { actor });
    case "END_TURN": return t("eventEndTurn", { actor });
    case "CONCEDE": return t("eventConcede", { actor });
    default: return t("eventUnknown");
  }
}

function renderDetailEvents(events) {
  refs.detailEvents.replaceChildren();
  const safeEvents = Array.isArray(events) ? events : [];
  if (!safeEvents.length) {
    refs.detailEvents.append(element("li", "history-detail-empty", t("noEvents")));
    return;
  }
  safeEvents.forEach((event, index) => {
    const row = element("li", "history-event");
    const seq = number(event?.seq, index + 1);
    const turn = number(event?.turn, 0);
    row.append(
      element("span", "history-event-seq", `#${seq}`),
      element("span", "history-event-text", eventText(event)),
      element("span", "history-event-turn", turn ? t("fieldTurn") + " " + turn : ""),
    );
    refs.detailEvents.append(row);
  });
}

function renderDetail(match, events = []) {
  if (!match) {
    refs.detail.hidden = true;
    return;
  }
  refs.detail.hidden = false;
  refs.detailSummary.textContent = detailSummary(match);
  refs.detailStatus.textContent = "";
  model.detailEvents = Array.isArray(events) ? events : [];
  renderDetailEvents(model.detailEvents);
}

async function loadAccountSession() {
  try {
    const payload = await request("/api/account/session");
    model.account = accountFromPayload(payload);
  } catch (_error) {
    redirectToAccount();
    return false;
  }
  if (!model.account) {
    redirectToAccount();
    return false;
  }
  renderAccountControls();
  return true;
}

async function loadMatches({ offset = model.offset } = {}) {
  if (model.busy) return;
  const generation = ++model.listGeneration;
  model.offset = Math.max(0, number(offset, 0));
  setError("");
  setStatus(t("loading"));
  setBusy(true);
  try {
    const query = new URLSearchParams({ offset: String(model.offset), limit: String(model.limit) });
    const payload = await request(`/api/matches?${query.toString()}`);
    if (generation !== model.listGeneration) return;
    model.matches = Array.isArray(payload?.matches) ? payload.matches.map(normalizeMatch).filter((match) => match.gameId) : [];
    model.offset = Math.max(0, number(payload?.offset, model.offset));
    model.limit = Math.max(1, number(payload?.limit, model.limit));
    model.total = Math.max(0, number(payload?.total, model.matches.length));
    renderMatches();
    setStatus("");
  } catch (error) {
    if (error.status === 401) {
      redirectToAccount();
      return;
    }
    model.matches = [];
    renderMatches();
    setError(t("requestFailed", { message: errorMessage(error) }));
    setStatus("");
  } finally {
    if (generation === model.listGeneration) setBusy(false);
  }
}

async function loadDetail(match) {
  if (model.busy || !match?.gameId) return;
  const generation = ++model.detailGeneration;
  model.detailMatch = match;
  renderDetail(match, []);
  refs.detailStatus.textContent = t("loadingDetail");
  const reducedMotion = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  refs.detail.scrollIntoView({ block: "start", behavior: reducedMotion ? "auto" : "smooth" });
  setBusy(true);
  try {
    const query = new URLSearchParams({ game_id: match.gameId });
    const payload = await request(`/api/matches/detail?${query.toString()}`);
    if (generation !== model.detailGeneration) return;
    const safeMatch = normalizeMatch(payload?.match || match);
    model.detailMatch = safeMatch;
    renderDetail(safeMatch, payload?.events);
  } catch (error) {
    if (error.status === 401) {
      redirectToAccount();
      return;
    }
    refs.detailStatus.textContent = t("detailFailed", { message: errorMessage(error) });
    renderDetailEvents([]);
  } finally {
    if (generation === model.detailGeneration) setBusy(false);
  }
}

function safeMatchUrl(value) {
  const candidate = text(value);
  return candidate === "/?arena=1" || candidate === "/" ? candidate : "/";
}

async function resumeMatch(match) {
  if (model.busy || !match?.gameId) return;
  setError("");
  setStatus(t("continueMatch"));
  setBusy(true);
  try {
    const payload = await request("/api/matches/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: match.gameId, revision: match.revision }),
    });
    window.location.assign(safeMatchUrl(payload?.match_url));
  } catch (error) {
    if (error.status === 401) {
      redirectToAccount();
      return;
    }
    setError(t("resumeFailed", { message: errorMessage(error) }));
    setStatus("");
  } finally {
    setBusy(false);
  }
}

function openConfirm(match, source) {
  if (model.busy || !match?.gameId) return;
  model.confirmMatch = match;
  model.confirmPreviousFocus = source;
  refs.confirmDescription.textContent = match.mode === "arena" ? t("abandonArenaWarning") : t("abandonDescription");
  refs.confirmShell.hidden = false;
  refs.confirmSubmit.focus();
}

function closeConfirm({ restoreFocus = true } = {}) {
  refs.confirmShell.hidden = true;
  const focus = model.confirmPreviousFocus;
  model.confirmMatch = null;
  model.confirmPreviousFocus = null;
  if (restoreFocus && focus && focus.isConnected && typeof focus.focus === "function") focus.focus();
}

async function abandonMatch() {
  const match = model.confirmMatch;
  if (model.busy || !match?.gameId) return;
  setError("");
  setStatus(t("abandonConfirm"));
  setBusy(true);
  try {
    await request("/api/matches/abandon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: match.gameId, revision: match.revision }),
    });
    closeConfirm({ restoreFocus: false });
    setBusy(false);
    await loadMatches({ offset: model.offset });
    if (refs.error.hidden) setStatus(t("abandonDone"));
  } catch (error) {
    if (error.status === 401) {
      redirectToAccount();
      return;
    }
    setError(t("abandonFailed", { message: errorMessage(error) }));
    setStatus("");
    setBusy(false);
  }
}

async function logout() {
  if (model.busy) return;
  setBusy(true);
  try {
    await request("/api/account/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    announceAccountChange();
  } catch (_error) {
    // The account route will still enforce authentication after navigation.
  }
  window.location.replace(accountUrl());
}

refs.list.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]");
  if (!action || !refs.list.contains(action)) return;
  event.preventDefault();
  const gameId = action.dataset.gameId;
  const match = model.matches.find((candidate) => candidate.gameId === gameId);
  if (!match) return;
  if (action.dataset.action === "resume") void resumeMatch(match);
  else if (action.dataset.action === "detail") void loadDetail(match);
  else if (action.dataset.action === "abandon") openConfirm(match, action);
});

refs.previous.addEventListener("click", () => {
  if (!model.busy) void loadMatches({ offset: Math.max(0, model.offset - model.limit) });
});
refs.next.addEventListener("click", () => {
  if (!model.busy) void loadMatches({ offset: model.offset + model.limit });
});
refs.refresh.addEventListener("click", () => { if (!model.busy) void loadMatches({ offset: model.offset }); });
refs.detailClose.addEventListener("click", () => {
  model.detailGeneration += 1;
  model.detailMatch = null;
  refs.detail.hidden = true;
});
refs.confirmCancel.addEventListener("click", () => closeConfirm());
refs.confirmSubmit.addEventListener("click", () => { void abandonMatch(); });
refs.confirmShell.addEventListener("click", (event) => {
  if (event.target?.dataset?.confirmClose === "true") closeConfirm();
});
refs.accountLogout.addEventListener("click", () => { void logout(); });
refs.localeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (model.busy || !COPY[button.dataset.locale]) return;
    model.locale = button.dataset.locale;
    storeLocale(model.locale);
    renderStaticCopy();
    renderMatches();
    if (model.detailMatch) renderDetail(model.detailMatch, model.detailEvents);
    if (model.confirmMatch) refs.confirmDescription.textContent = model.confirmMatch.mode === "arena" ? t("abandonArenaWarning") : t("abandonDescription");
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!refs.confirmShell.hidden) closeConfirm();
  else if (!refs.detail.hidden) refs.detailClose.click();
});

renderStaticCopy();
setStatus(t("loading"));

void (async () => {
  if (!(await loadAccountSession())) return;
  watchAccountSession(model.account.id, redirectToAccount);
  await loadMatches({ offset: 0 });
  const requestedGameId = new URLSearchParams(window.location.search).get("game_id");
  const requested = model.matches.find((match) => match.gameId === requestedGameId);
  if (requested) void loadDetail(requested);
})();

window.historyPage = {
  loadMatches,
  loadDetail,
  normalizeMatch,
};
