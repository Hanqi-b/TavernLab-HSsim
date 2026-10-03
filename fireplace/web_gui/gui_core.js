import { announceAccountChange, watchAccountSession } from "./account_session.js";

const ELEMENT_IDS = [
  "app-shell", "lobby-screen", "lobby-form", "lobby-title", "lobby-subtitle",
  "nickname-input", "nickname-label", "nickname-hint", "language-label",
  "locale-zhCN", "locale-enUS", "opponent-label", "opponent-select", "opponent-hint",
  "start-match-button", "lobby-status", "lobby-footer", "lobby-login-actions",
  "lobby-account-toolbar", "lobby-account-label", "lobby-account-import", "lobby-account-logout",
  "enter-lobby-button", "lobby-setup", "lobby-mode-navigation", "battle-entry",
  "battle-entry-title", "battle-entry-description", "arena-entry", "arena-entry-title",
  "arena-entry-description", "collection-entry", "collection-entry-title",
  "collection-entry-description", "history-entry", "history-entry-title", "history-entry-description",
  "deck-choice-field", "deck-label", "deck-select", "deck-hint",
  "game", "table", "page-title", "brand-caption",
  "match-account-toolbar", "match-account-label", "match-account-import", "match-account-logout",
  "opponent-title", "self-title", "phase-value", "turn-value", "active-seat-value",
  "revision-value", "notice", "opponent-hand-count", "opponent-deck-count", "opponent-mana-value", "opponent-hand",
  "opponent-hero-status", "opponent-hero-row", "opponent-extras", "opponent-board-count",
  "opponent-board", "self-hero-row", "self-hero-status", "self-extras", "self-board-count",
  "self-board", "hand-title", "decision-title", "log-title", "hero-power-row", "mana-value",
  "hand", "deck-count", "action-count", "decision-panel", "action-instructions",
  "selection-summary", "quick-actions", "choice-options", "position-choices", "target-hint",
  "action-submit", "selection-cancel", "end-turn-button", "pending-choice", "action-menu",
  "surrender-menu", "surrender-title", "surrender-description", "surrender-continue", "surrender-confirm",
  "fallback-count", "event-log", "game-over", "game-over-message", "game-over-return",
  "game-over-dismiss", "terminal-actions", "terminal-status", "terminal-return", "connection-value",
  "card-modal", "modal-close", "modal-art", "modal-card-name", "modal-card-id", "modal-stats",
  "modal-statuses", "modal-modifiers", "modal-card-text",
];

export function collectElements(document) {
  return Object.fromEntries(ELEMENT_IDS.map((id) => [id, document.getElementById(id)]));
}

/** Lobby and DOM shell. Network lifecycle is injected as callbacks. */
export function createLobby({
  document, window, elements, locale, dom, state, decisions, modal,
  onLoadState, onPollState, onStartMatch, onReturnHome,
  onInitAttackLine, onRenderSnapshot, onRenderEmptyState, onResetAssets,
  onConcede, getBusy,
}) {
  let currentMode = "lobby";
  let lobbyStage = "login";
  let pollTimer = null;
  let deckRequestGeneration = 0;
  let deckState = "loading";
  let availableDecks = [];
  let account = null;
  let legacyAvailable = false;
  let surrenderReturnFocus = null;
  const preferredDeckId = requestedDeckId();
  const opponentStorageKey = "fireplace.opponent";
  const opponentIds = new Set(["radical", "mcts"]);

  async function init() {
    if (!(await ensureAccount())) return;
    watchAccountSession(account.id, () => { window.location.replace(accountUrl()); });
    bindLobbyControls();
    bindAccountControls();
    onInitAttackLine();
    elements["action-submit"].addEventListener("click", decisions.submitSelected);
    elements["selection-cancel"].addEventListener("click", decisions.cancelSelection);
    elements["end-turn-button"].addEventListener("click", decisions.submitEndTurn);
    elements["modal-close"].addEventListener("click", modal.closeCardModal);
    elements["game-over-dismiss"].addEventListener("click", () => {
      state.dismissOutcome();
      dom.setHidden(elements["game-over"], true);
      dom.setHidden(elements["terminal-actions"], false);
    });
    elements["game-over-return"].addEventListener("click", onReturnHome);
    elements["terminal-return"].addEventListener("click", onReturnHome);
    elements["card-modal"].addEventListener("click", (event) => {
      if (event.target && event.target.getAttribute("data-modal-close") === "true") {
        modal.closeCardModal();
      }
    });
    elements["surrender-continue"].addEventListener("click", () => closeSurrenderMenu());
    elements["surrender-confirm"].addEventListener("click", () => {
      if (typeof onConcede !== "function" || (typeof getBusy === "function" && getBusy())) return;
      closeSurrenderMenu();
      void onConcede();
    });
    elements["surrender-menu"].addEventListener("click", (event) => {
      if (event.target && event.target.getAttribute("data-surrender-close") === "true") {
        closeSurrenderMenu();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Tab" && isSurrenderMenuOpen()) {
        trapSurrenderFocus(event);
        return;
      }
      if (event.key !== "Escape") return;
      if (!elements["card-modal"].hidden) {
        event.preventDefault();
        modal.closeCardModal();
      } else if (selectionActive()) {
        event.preventDefault();
        decisions.cancelSelection();
      } else if (isSurrenderMenuOpen()) {
        event.preventDefault();
        closeSurrenderMenu();
      } else if (canOpenSurrenderMenu()) {
        event.preventDefault();
        openSurrenderMenu();
      }
    });
    applyLocaleToDocument();
    setLobbyFormValues();
    bindModeNavigation();
    bindDeckSelection();
    bindOpponentSelection();
    renderDeckOptions();
    syncOpponentSelection();
    loadDeckOptions();
    onLoadState(false);
    pollTimer = window.setInterval(onPollState, 2500);
  }

  function currentPath() {
    const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    return path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") ? path : "/";
  }

  function accountUrl() {
    return `/account?next=${encodeURIComponent(currentPath() === "/" ? "/" : currentPath())}`;
  }

  function nicknameStorageKey() {
    return `fireplace.nickname.${account?.id || "anonymous"}`;
  }

  async function accountRequest(path, options = {}) {
    const response = await window.fetch(path, {
      ...options,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      cache: "no-store",
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* empty response */ }
    if (!response.ok) {
      const message = payload?.error?.message || payload?.message || payload?.error || `${response.status}`;
      const error = new Error(String(message));
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function setAccountToolbar(toolbarId, labelId, importId, logoutId) {
    const toolbar = elements[toolbarId];
    const label = elements[labelId];
    const importButton = elements[importId];
    const logoutButton = elements[logoutId];
    if (!toolbar) return;
    dom.setHidden(toolbar, !account);
    if (label) {
      dom.setText(label, account ? account.username : "");
      label.href = "/account";
      label.setAttribute("aria-label", account ? `${locale.tr("account.open")}: ${account.username}` : "");
    }
    if (logoutButton) dom.setText(logoutButton, locale.tr("account.logout"));
    if (importButton) {
      dom.setText(importButton, locale.tr("account.importLegacy"));
      dom.setHidden(importButton, !account || !legacyAvailable);
      importButton.title = locale.tr("account.importLegacyHint");
    }
  }

  function renderAccountControls() {
    setAccountToolbar("lobby-account-toolbar", "lobby-account-label", "lobby-account-import", "lobby-account-logout");
    setAccountToolbar("match-account-toolbar", "match-account-label", "match-account-import", "match-account-logout");
  }

  async function ensureAccount() {
    try {
      const payload = await accountRequest("/api/account/session");
      const raw = payload?.account;
      const username = raw && typeof raw.username === "string" ? raw.username.trim() : "";
      const id = raw && typeof raw.id === "string" ? raw.id.trim() : "";
      account = payload?.authenticated && username && id ? { id, username } : null;
      legacyAvailable = payload?.legacy_available === true;
    } catch (_error) {
      account = null;
      legacyAvailable = false;
    }
    if (!account) {
      window.location.replace(accountUrl());
      return false;
    }
    renderAccountControls();
    return true;
  }

  function bindAccountControls() {
    ["lobby-account-logout", "match-account-logout"].forEach((id) => {
      const button = elements[id];
      if (button) button.addEventListener("click", () => { void logoutAccount(); });
    });
    ["lobby-account-import", "match-account-import"].forEach((id) => {
      const button = elements[id];
      if (button) button.addEventListener("click", () => { void importLegacy(); });
    });
  }

  async function logoutAccount() {
    try {
      await accountRequest("/api/account/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      announceAccountChange();
    } catch (_error) {
      // The redirect clears the private page even if the server is already unavailable.
    }
    window.location.replace("/account?next=%2F");
  }

  async function importLegacy() {
    if (!legacyAvailable || !account || !window.confirm(locale.tr("account.importLegacyConfirm"))) return;
    ["lobby-account-import", "match-account-import"].forEach((id) => {
      if (elements[id]) elements[id].disabled = true;
    });
    try {
      await accountRequest("/api/account/import-legacy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: account.id }),
      });
      legacyAvailable = false;
      renderAccountControls();
      setLobbyStatus(locale.tr("account.importLegacyDone"));
      if (currentMode === "lobby") loadDeckOptions();
    } catch (error) {
      setLobbyStatus(locale.tr("account.importLegacyFailed", { message: error.message || locale.tr("account.network") }), "error");
    }
  }

  function bindLobbyControls() {
    elements["lobby-form"].addEventListener("submit", (event) => {
      event.preventDefault();
      if (lobbyStage === "login") enterLobby();
      else if (!(elements["nickname-input"]?.value || "").trim()) enterLobby();
      else onStartMatch();
    });
    ["locale-zhCN", "locale-enUS"].forEach((id) => {
      elements[id].addEventListener("click", () => {
        if (currentMode === "match") return;
        setLocale(elements[id].getAttribute("data-locale"), true);
      });
    });
  }

  function bindModeNavigation() {
    const battleEntry = elements["battle-entry"];
    if (!battleEntry) return;
    battleEntry.addEventListener("click", () => {
      battleEntry.classList.add("is-selected");
      battleEntry.setAttribute("aria-expanded", "true");
      const input = elements["nickname-input"];
      if (input && typeof input.focus === "function") input.focus();
    });
  }

  function bindDeckSelection() {
    const select = elements["deck-select"];
    if (!select) return;
    select.addEventListener("change", () => {
      select.dataset.userSelected = "true";
    });
  }

  function validOpponent(value) {
    const candidate = String(value || "").trim();
    return opponentIds.has(candidate) ? candidate : "radical";
  }

  function opponentSelectionPreference() {
    const select = elements["opponent-select"];
    if (select && select.value && select.dataset.userSelected === "true") {
      return validOpponent(select.value);
    }
    return validOpponent(locale.readStored(opponentStorageKey, "radical"));
  }

  function syncOpponentSelection() {
    const select = elements["opponent-select"];
    if (!select) return;
    const selected = opponentSelectionPreference();
    select.value = selected;
    ["radical", "mcts"].forEach((kind) => {
      const option = select.querySelector(`option[value="${kind}"]`);
      if (option) dom.setText(option, locale.tr(`lobby.${kind}`));
    });
    dom.setText(elements["opponent-hint"], locale.tr(`lobby.${selected}Description`));
    select.setAttribute("aria-label", locale.tr("lobby.opponent"));
  }

  function bindOpponentSelection() {
    const select = elements["opponent-select"];
    if (!select) return;
    select.addEventListener("change", () => {
      const selected = validOpponent(select.value);
      select.value = selected;
      select.dataset.userSelected = "true";
      locale.writeStored(opponentStorageKey, selected);
      syncOpponentSelection();
    });
  }

  function deckSelectionPreference() {
    const select = elements["deck-select"];
    if (select && select.dataset.userSelected === "true") return select.value || "";
    return preferredDeckId || (select ? select.value : "") || "";
  }

  function requestedDeckId() {
    const value = new URLSearchParams(window.location.search).get("deck");
    return value ? value.trim() : "";
  }

  function deckCardCount(deck) {
    if (!deck || typeof deck !== "object") return 0;
    if (Array.isArray(deck.card_ids)) return deck.card_ids.length;
    if (Array.isArray(deck.cards)) return deck.cards.length;
    return 0;
  }

  function deckDisplayName(deck) {
    const name = deck && deck.name ? String(deck.name) : locale.tr("lobby.unnamedDeck");
    const rawHero = deck && deck.hero ? deck.hero : null;
    const hero = rawHero && typeof rawHero === "object"
      ? String(rawHero.name || rawHero.card_id || deck.hero_id || "")
      : (rawHero ? String(rawHero) : String(deck && deck.hero_id ? deck.hero_id : ""));
    const count = deckCardCount(deck);
    return hero ? `${name} · ${hero} · ${count}` : `${name} · ${count}`;
  }

  function renderDeckOptions(preferred) {
    const select = elements["deck-select"];
    if (!select) return;
    const current = preferred === undefined ? select.value : preferred;
    dom.clear(select);
    const random = document.createElement("option");
    random.value = "";
    random.textContent = locale.tr("lobby.randomDeck");
    select.appendChild(random);
    availableDecks.forEach((deck) => {
      if (!deck || deck.complete !== true || !deck.id) return;
      const option = document.createElement("option");
      option.value = String(deck.id);
      option.textContent = deckDisplayName(deck);
      select.appendChild(option);
    });
    const validSelection = availableDecks.some((deck) =>
      deck && deck.complete === true && String(deck.id) === String(current));
    select.value = validSelection ? String(current) : "";
    if (elements["deck-hint"]) {
      let hint = locale.tr("lobby.deckLoading");
      if (deckState === "ready") {
        hint = availableDecks.some((deck) => deck && deck.complete === true)
          ? locale.tr("lobby.deckHint")
          : locale.tr("lobby.noSavedDeck");
      } else if (deckState === "error") {
        hint = locale.tr("lobby.deckUnavailable");
      }
      dom.setText(elements["deck-hint"], hint);
    }
  }

  function loadDeckOptions() {
    const generation = ++deckRequestGeneration;
    deckState = "loading";
    renderDeckOptions(deckSelectionPreference());
    const query = encodeURIComponent(locale.locale);
    return window.fetch(`/api/decks?locale=${query}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
      .then((response) => response.text().then((body) => {
        let payload = {};
        if (body) payload = JSON.parse(body);
        if (!response.ok) throw new Error(dataErrorMessage(payload));
        return payload;
      }))
      .then((payload) => {
        if (generation !== deckRequestGeneration) return;
        availableDecks = Array.isArray(payload && payload.decks) ? payload.decks : [];
        deckState = "ready";
        renderDeckOptions(deckSelectionPreference());
      })
      .catch(() => {
        if (generation !== deckRequestGeneration) return;
        availableDecks = [];
        deckState = "error";
        renderDeckOptions("");
      });
  }

  function dataErrorMessage(payload) {
    if (payload && typeof payload.error === "string") return payload.error;
    return `HTTP ${locale.tr("lobby.deckUnavailable")}`;
  }

  function setLocale(value, persist) {
    if (currentMode === "match" && value !== locale.locale) return;
    locale.setLocale(value);
    if (persist) locale.writeStored("fireplace.locale", locale.locale);
    applyLocaleToDocument();
    updateLocaleControls();
    if (currentMode === "lobby") {
      renderLobby();
      loadDeckOptions();
    }
    else if (state.current.snapshot) onRenderSnapshot();
  }

  function applyLocaleToDocument() {
    document.documentElement.lang = locale.locale === "enUS" ? "en" : "zh-CN";
    document.title = "Fireplace · " + locale.tr("app.title");
    const description = document.querySelector("meta[name=description]");
    if (description) description.setAttribute("content", locale.tr("app.description"));
    renderStaticCopy();
    renderDeckOptions(deckSelectionPreference());
  }

  function setSelectorText(selector, value) {
    const node = document.querySelector(selector);
    if (node) dom.setText(node, value);
  }

  function renderStaticCopy() {
    dom.setText(elements["page-title"], locale.tr("app.title"));
    dom.setText(elements["brand-caption"], locale.tr("app.caption"));
    dom.setText(elements["opponent-title"], locale.tr("opponent"));
    dom.setText(elements["self-title"], locale.tr("you"));
    dom.setText(elements["hand-title"], locale.tr("yourHand"));
    dom.setText(elements["decision-title"], locale.tr("decision"));
    dom.setText(elements["log-title"], locale.tr("matchLog"));
    dom.setText(elements["game-over-return"], locale.tr("returnHome"));
    dom.setText(elements["game-over-dismiss"], locale.tr("viewBoard"));
    dom.setText(elements["terminal-status"], locale.tr("terminalStatus"));
    dom.setText(elements["terminal-return"], locale.tr("returnHome"));
    dom.setText(elements["surrender-title"], locale.tr("surrender.title"));
    dom.setText(elements["surrender-description"], locale.tr("surrender.description"));
    dom.setText(elements["surrender-continue"], locale.tr("surrender.continue"));
    dom.setText(elements["surrender-confirm"], locale.tr("surrender.confirm"));
    dom.setText(elements["battle-entry-title"], locale.tr("lobby.battle"));
    dom.setText(elements["battle-entry-description"], locale.tr("lobby.battleDescription"));
    dom.setText(elements["arena-entry-title"], locale.tr("lobby.arena"));
    dom.setText(elements["arena-entry-description"], locale.tr("lobby.arenaDescription"));
    dom.setText(elements["collection-entry-title"], locale.tr("lobby.collection"));
    dom.setText(elements["collection-entry-description"], locale.tr("lobby.collectionDescription"));
    dom.setText(elements["history-entry-title"], locale.tr("lobby.history"));
    dom.setText(elements["history-entry-description"], locale.tr("lobby.historyDescription"));
    renderAccountControls();
    if (elements["lobby-mode-navigation"]) {
      elements["lobby-mode-navigation"].setAttribute("aria-label", locale.tr("lobby.modesAria"));
    }
    dom.setText(elements["deck-label"], locale.tr("lobby.deckLabel"));
    if (elements["deck-select"]) elements["deck-select"].setAttribute("aria-label", locale.tr("lobby.deckLabel"));
    syncOpponentSelection();
    setSelectorText(".opponent-panel .board-heading h3", locale.tr("opponentBoard"));
    setSelectorText(".self-panel .board-heading h3", locale.tr("yourBoard"));
    setSelectorText(".log-section .section-heading .muted", locale.tr("logRecent"));
    setSelectorText(".game-over-card .eyebrow", locale.tr("matchComplete"));
    setSelectorText(".game-over-card h2", locale.tr("gameOver"));
    setSelectorText(".game-over-card .muted", locale.tr("gameOverHint"));
    setSelectorText(".footer > span:first-child", locale.tr("footer"));
    const fallbackSummary = document.querySelector("#action-fallback summary");
    if (fallbackSummary) {
      const fallbackCount = elements["fallback-count"];
      dom.clear(fallbackSummary);
      fallbackSummary.appendChild(document.createTextNode(locale.tr("fallback") + " "));
      if (fallbackCount) fallbackSummary.appendChild(fallbackCount);
    }
    setSelectorText(".modal-copy .eyebrow", locale.tr("cardDetail"));
    const labels = [
      ["table", "yourBoard"], ["opponent-hand", "opponentHandAria"], ["opponent-hand-count", "opponentHandCount"],
      ["opponent-board", "opponentBoard"], ["self-board", "yourBoard"], ["hand", "yourHand"],
      ["modal-close", "close"], ["opponent-mana-value", "opponentManaAria"], ["mana-value", "yourManaAria"],
      ["opponent-extras", "opponentExtrasAria"], ["self-extras", "yourExtrasAria"],
      ["opponent-hero-status", "opponentHeroStatusesAria"], ["self-hero-status", "yourHeroStatusesAria"],
      ["choice-options", "choiceOptions"], ["quick-actions", "quickActions"], ["position-choices", "positions"],
    ];
    labels.forEach(([id, key]) => {
      if (elements[id]) elements[id].setAttribute("aria-label", locale.tr(key));
    });
    const belowTools = document.querySelector(".below-board-tools");
    if (belowTools) belowTools.setAttribute("aria-label", locale.tr("backupActions"));
  }

  function updateLocaleControls() {
    ["zhCN", "enUS"].forEach((value) => {
      const button = elements[`locale-${value}`];
      if (!button) return;
      const selected = value === locale.locale;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function setLobbyFormValues() {
    const input = elements["nickname-input"];
    if (!input) return;
    input.value = locale.readStored(nicknameStorageKey(), "") || (account ? account.username : "");
    syncOpponentSelection();
    setLobbyStage(input.value.trim() || preferredDeckId ? "setup" : "login");
    updateLocaleControls();
  }

  function setLobbyStage(stage) {
    lobbyStage = stage === "setup" ? "setup" : "login";
    dom.setHidden(elements["lobby-login-actions"], lobbyStage !== "login");
    dom.setHidden(elements["lobby-setup"], lobbyStage !== "setup");
    dom.setText(elements["enter-lobby-button"], locale.tr("lobby.enter"));
  }

  function setLobbyStatus(message, kind) {
    dom.setText(elements["lobby-status"], message || "");
    elements["lobby-status"].className = `lobby-status${kind ? ` ${kind}` : ""}`;
  }

  function setScreen(mode) {
    currentMode = mode === "match" ? "match" : "lobby";
    if (currentMode === "lobby" || (state.current.snapshot && state.current.snapshot.outcome)) {
      closeSurrenderMenu({ restoreFocus: false });
    }
    dom.setHidden(elements["lobby-screen"], currentMode !== "lobby");
    dom.setHidden(elements.game, currentMode !== "match");
    if (currentMode === "lobby") {
      dom.setHidden(elements["game-over"], true);
      dom.setHidden(elements["terminal-actions"], true);
      updateLocaleControls();
    }
  }

  function clearMatchState() {
    closeSurrenderMenu({ restoreFocus: false });
    state.resetMatch();
    modal.reset();
    dom.setHidden(elements["terminal-actions"], true);
    onResetAssets();
    onRenderEmptyState();
  }

  function renderLobby() {
    setScreen("lobby");
    const copy = [
      ["lobby-title", "lobby.title"], ["lobby-subtitle", "lobby.subtitle"], ["nickname-label", "lobby.nickname"],
      ["nickname-hint", "lobby.nicknameHint"], ["language-label", "lobby.language"], ["opponent-label", "lobby.opponent"],
      ["start-match-button", "lobby.start"], ["lobby-footer", "lobby.footer"],
      ["history-entry-title", "lobby.history"], ["history-entry-description", "lobby.historyDescription"],
      ["deck-label", "lobby.deckLabel"],
      ["surrender-title", "surrender.title"], ["surrender-description", "surrender.description"],
      ["surrender-continue", "surrender.continue"], ["surrender-confirm", "surrender.confirm"],
    ];
    copy.forEach(([id, key]) => dom.setText(elements[id], locale.tr(key)));
    elements["nickname-input"].placeholder = locale.tr("lobby.nicknamePlaceholder");
    renderDeckOptions(deckSelectionPreference());
    syncOpponentSelection();
    updateLocaleControls();
    setLobbyStage(lobbyStage);
  }

  function selectionActive() {
    const selection = state.current.selection || {};
    return Boolean(selection.type || selection.sourceId !== null || selection.branchId !== null ||
      selection.targetId !== null || selection.position !== null ||
      (Array.isArray(selection.mulliganIds) && selection.mulliganIds.length));
  }

  function canOpenSurrenderMenu() {
    const snapshot = state.current.snapshot;
    const phase = snapshot && snapshot.observation ? String(snapshot.observation.phase || "") : "";
    return currentMode === "match" && Boolean(snapshot) && !snapshot.outcome && phase !== "GAME_OVER" &&
      !(typeof getBusy === "function" && getBusy());
  }

  function isSurrenderMenuOpen() {
    return Boolean(elements["surrender-menu"] && !elements["surrender-menu"].hidden);
  }

  function surrenderMenuButtons() {
    return [elements["surrender-continue"], elements["surrender-confirm"]]
      .filter((button) => button && !button.disabled && !button.hidden);
  }

  function canRestoreFocus(node) {
    return Boolean(node && node.isConnected && !node.disabled && !node.hidden &&
      !node.closest("[hidden]") && typeof node.focus === "function");
  }

  function fallbackSurrenderFocus() {
    return [elements["action-submit"], elements["selection-cancel"], elements["end-turn-button"], elements.game]
      .find((node) => canRestoreFocus(node));
  }

  function trapSurrenderFocus(event) {
    const buttons = surrenderMenuButtons();
    if (!buttons.length) return;
    const current = document.activeElement;
    const index = buttons.indexOf(current);
    if (event.shiftKey && (index <= 0 || index < 0)) {
      event.preventDefault();
      buttons[buttons.length - 1].focus();
    } else if (!event.shiftKey && (index === buttons.length - 1 || index < 0)) {
      event.preventDefault();
      buttons[0].focus();
    }
  }

  function openSurrenderMenu() {
    if (!canOpenSurrenderMenu() || isSurrenderMenuOpen()) return;
    const active = document.activeElement;
    surrenderReturnFocus = active && active !== document.body && canRestoreFocus(active) ? active : null;
    dom.setHidden(elements["surrender-menu"], false);
    elements["surrender-continue"].focus();
  }

  function closeSurrenderMenu({ restoreFocus = true } = {}) {
    if (!elements["surrender-menu"] || elements["surrender-menu"].hidden) return;
    dom.setHidden(elements["surrender-menu"], true);
    const previous = surrenderReturnFocus;
    surrenderReturnFocus = null;
    if (restoreFocus) (canRestoreFocus(previous) ? previous : fallbackSurrenderFocus())?.focus();
  }

  function enterLobby() {
    const input = elements["nickname-input"];
    const nickname = input ? input.value.trim() : "";
    if (!nickname) {
      setLobbyStatus(locale.tr("lobby.enterName"), "error");
      if (input) input.focus();
      return;
    }
    locale.writeStored(nicknameStorageKey(), nickname);
    setLobbyStage("setup");
    setLobbyStatus(locale.tr("lobby.serverReady"));
  }

  return {
    applyLocaleToDocument, clearMatchState, enterLobby, init, renderLobby,
    renderStaticCopy, setLobbyFormValues, setLobbyStage, setLobbyStatus,
    setLocale, setScreen, setSelectorText, updateLocaleControls,
    nickname() {
      const value = elements["nickname-input"] ? elements["nickname-input"].value.trim() : "";
      if (value) locale.writeStored(nicknameStorageKey(), value);
      return value;
    },
    opponent() {
      const select = elements["opponent-select"];
      const value = validOpponent(select ? select.value : opponentSelectionPreference());
      locale.writeStored(opponentStorageKey, value);
      return value;
    },
    get mode() { return currentMode; },
    get lobbyStage() { return lobbyStage; },
    stop() { if (pollTimer !== null) window.clearInterval(pollTimer); },
  };
}
