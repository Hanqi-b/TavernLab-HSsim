const API = {
  state: "/api/state",
  action: "/api/action",
  start: "/api/start",
  concede: "/api/concede",
  returnHome: "/api/return",
};

/** Owns all HTTP requests, busy state, and revision synchronization. */
export function createSync({
  window, document, elements, state, locale, data, dom, cards,
  renderer, feedback, modal, getMode, onModeChange, onClearMatch,
  onApplyLocale, onRenderLobby, onSetLobbyFormValues, onSetLobbyStatus,
}) {
  let busy = false;
  let requestGeneration = 0;

  function readJsonResponse(response) {
    return response.text().then((body) => {
      let payload = {};
      if (body) {
        try {
          payload = JSON.parse(body);
        } catch (_error) {
          throw new Error(locale.tr("invalidJson", { value: response.status }));
        }
      }
      if (!response.ok) {
        const failure = new Error(data.errorMessage(payload.error) || `HTTP ${response.status}`);
        failure.payload = payload;
        failure.status = response.status;
        throw failure;
      }
      return payload;
    });
  }

  function snapshotFromPayload(payload) {
    if (!data.isObject(payload)) return null;
    if (data.isObject(payload.snapshot)) return snapshotFromPayload(payload.snapshot);
    if (!data.isObject(payload.observation) || !Array.isArray(payload.legal_actions)) return null;
    return {
      session_id: data.safeText(payload.session_id, ""),
      revision: data.safeNumber(payload.revision, 0),
      observation: payload.observation,
      legal_actions: payload.legal_actions,
      outcome: payload.outcome === undefined ? null : payload.outcome,
      events: Array.isArray(payload.events) ? payload.events : [],
    };
  }

  function normalizeServerPayload(payload) {
    if (!data.isObject(payload)) return { mode: "unknown", locale: locale.locale, snapshot: null };
    const mode = payload.mode === "lobby" ? "lobby" : "match";
    const selectedLocale = locale.normalizeLocale(payload.locale || locale.locale);
    if (mode === "lobby") return { mode, locale: selectedLocale, snapshot: null, raw: payload };
    const source = data.isObject(payload.snapshot) ? payload.snapshot : payload;
    return { mode, locale: selectedLocale, snapshot: snapshotFromPayload(source), raw: payload };
  }

  function applyServerPayload(payload, options) {
    const envelope = normalizeServerPayload(payload);
    if (envelope.mode === "lobby") {
      if (new URLSearchParams(window.location.search).get("arena") === "1") {
        window.location.assign("/arena");
        return envelope;
      }
      const enteredLobby = getMode() !== "lobby";
      if (enteredLobby || state.current.snapshot) {
        onClearMatch();
        if (enteredLobby) onSetLobbyFormValues();
      }
      locale.setLocale(envelope.locale || locale.locale);
      onApplyLocale();
      onRenderLobby();
      return envelope;
    }
    if (!envelope.snapshot) throw new Error(locale.tr("stateMissing"));
    if (getMode() !== "match") onClearMatch();
    locale.setLocale(envelope.locale || locale.locale);
    onApplyLocale();
    if (state.isStale(envelope.snapshot)) return envelope;
    applySnapshot(envelope.snapshot, options || { resetSelection: state.isDecisionChanged(envelope.snapshot) });
    onModeChange("match");
    return envelope;
  }

  function loadState(silent = false) {
    const generation = requestGeneration;
    if (!silent) dom.setConnection(locale.tr("status.reading"), false);
    return window.fetch(API.state, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return null;
        const envelope = normalizeServerPayload(payload);
        const result = applyServerPayload(payload, {
          resetSelection: envelope.snapshot ? state.isDecisionChanged(envelope.snapshot) : false,
        });
        dom.setConnection(locale.tr("status.connected"), false);
        return result.snapshot;
      })
      .catch((error) => {
        if (generation !== requestGeneration) return null;
        dom.setConnection(locale.tr("status.disconnected"), true);
        if (!silent || (!state.current.snapshot && getMode() !== "lobby")) {
          dom.showNotice(locale.tr("stateUnavailable", { message: data.errorMessage(error) }), "error", 0);
          if (!state.current.snapshot) onRenderLobby();
        }
        return null;
      });
  }

  function pollState() {
    if (busy) return;
    const generation = requestGeneration;
    return window.fetch(API.state, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return;
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode === "lobby") {
          if (getMode() !== "lobby") applyServerPayload(payload, { resetSelection: true });
          dom.setConnection(locale.tr("status.connected"), false);
          return;
        }
        const next = envelope.snapshot;
        if (!next || state.isStale(next)) return;
        dom.setConnection(locale.tr("status.connected"), false);
        if (dataFingerprint(next) !== state.current.fingerprint) {
          const hadSnapshot = Boolean(state.current.snapshot);
          const decisionChanged = state.isDecisionChanged(next);
          applyServerPayload(payload, { resetSelection: decisionChanged });
          if (decisionChanged && hadSnapshot && !busy) dom.showNotice(locale.tr("stateUpdated"), "", 3200);
        }
      })
      .catch(() => {
        if (generation === requestGeneration) dom.setConnection(locale.tr("status.disconnected"), true);
      });
  }

  function dataFingerprint(value) {
    try { return JSON.stringify(value); } catch (_error) { return String(Date.now()); }
  }

  function applySnapshot(next, options) {
    const transition = state.commit(next, options);
    const previous = transition.sessionChanged ? null : transition.previous;
    const previousEventSeq = transition.previousEventSeq;
    if (transition.sessionChanged) cards.resetAssets();
    const resetSelection = transition.resetSelection;
    let focusId = null;
    let focusEntityId = null;
    let focusInspectEntityId = null;
    let focusPosition = null;
    let focusActionKey = null;
    if (!resetSelection && document.activeElement) {
      const active = document.activeElement;
      focusId = active.id || null;
      focusEntityId = active.getAttribute && active.getAttribute("data-entity-id");
      if (active.classList && active.classList.contains("card-inspect")) {
        const card = active.closest("[data-entity-id]");
        focusInspectEntityId = card && card.getAttribute("data-entity-id");
      }
      focusPosition = active.getAttribute && active.getAttribute("data-position");
      focusActionKey = active.getAttribute && active.getAttribute("data-action-key");
    }
    renderer.renderSnapshot();
    modal.refreshOpenCardModal();
    feedback.showPublicFeedback(previous, next, previousEventSeq);
    if (!resetSelection) restoreFocus({ focusId, focusEntityId, focusInspectEntityId, focusPosition, focusActionKey });
    if (previous && transition.events.length) {
      const previousSeq = previousEventSeq === null ? -1 : previousEventSeq;
      if (transition.newestSeq > previousSeq) {
        dom.showNotice(renderer.eventText(transition.newest), transition.newest && transition.newest.actor === "opponent" ? "ai-event" : "", 2600);
      }
    }
  }

  function restoreFocus({ focusId, focusEntityId, focusInspectEntityId, focusPosition, focusActionKey }) {
    let focusNode = focusId ? document.getElementById(focusId) : null;
    if (!focusNode && focusEntityId) focusNode = document.querySelector(`[data-entity-id="${focusEntityId}"]`);
    if (!focusNode && focusInspectEntityId) focusNode = document.querySelector(`[data-entity-id="${focusInspectEntityId}"] .card-inspect`);
    if (!focusNode && focusPosition !== null) {
      focusNode = Array.from(document.querySelectorAll("[data-position]"))
        .find((node) => node.getAttribute("data-position") === focusPosition);
    }
    if (!focusNode && focusActionKey) {
      focusNode = Array.from(document.querySelectorAll("[data-action-key]"))
        .find((node) => node.getAttribute("data-action-key") === focusActionKey);
    }
    if (focusNode && typeof focusNode.focus === "function") focusNode.focus();
  }

  function setButtonsDisabled(disabled) {
    document.querySelectorAll("button").forEach((button) => { button.disabled = Boolean(disabled); });
  }

  function submitAction(index) {
    const snapshot = state.current.snapshot;
    const action = state.current.actionIndex.actions[index];
    if (busy || !snapshot) return;
    if (!data.isObject(action)) {
      dom.showNotice(locale.tr("staleRevision"), "error", 0);
      loadState(false);
      return;
    }
    const generation = requestGeneration;
    busy = true;
    setButtonsDisabled(true);
    dom.setConnection(locale.tr("status.submitting"), false);
    return window.fetch(API.action, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: snapshot.session_id, revision: snapshot.revision, action }),
    })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return;
        const envelope = applyServerPayload(payload, { resetSelection: true });
        if (envelope.mode !== "match" || !envelope.snapshot) throw new Error(locale.tr("actionMissing"));
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation !== requestGeneration) return;
        let synced = false;
        if (error && error.payload) {
          const envelope = normalizeServerPayload(error.payload);
          if (envelope.mode === "lobby" || envelope.snapshot) {
            applyServerPayload(error.payload, { resetSelection: true });
            synced = true;
          }
        }
        if (error && error.status === 409) dom.showNotice(locale.tr("staleAction"), "error", 0);
        else dom.showNotice(locale.tr("submitFailed", { message: data.errorMessage(error) }), "error", 0);
        if (error && error.status === 409 && synced) dom.setConnection(locale.tr("status.connected"), false);
        else dom.setConnection(error && error.status ? locale.tr("status.rejected") : locale.tr("status.disconnected"), true);
        if (!synced) loadState(false);
      })
      .finally(() => {
        if (generation !== requestGeneration) return;
        busy = false;
        setButtonsDisabled(false);
      });
  }

  function startMatch(nickname) {
    if (busy) return;
    if (!nickname) return;
    const generation = ++requestGeneration;
    busy = true;
    elements["start-match-button"].disabled = true;
    onSetLobbyStatus(locale.tr("lobby.starting"));
    dom.setConnection(locale.tr("status.connecting"), false);
    const selectedDeck = document.getElementById("deck-select");
    const deckId = selectedDeck && typeof selectedDeck.value === "string"
      ? selectedDeck.value.trim()
      : "";
    const body = { nickname, locale: locale.locale };
    // Keep the legacy random-match request byte-for-byte compatible.  A deck
    // identifier is sent only when the user explicitly chose a saved deck.
    if (deckId) body.deck_id = deckId;
    return window.fetch(API.start, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return;
        const envelope = normalizeServerPayload(payload);
        if (!envelope.snapshot) throw new Error(locale.tr("stateMissing"));
        locale.setLocale(envelope.locale || locale.locale);
        onApplyLocale();
        onClearMatch();
        applySnapshot(envelope.snapshot, { resetSelection: true });
        onModeChange("match");
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation !== requestGeneration) return;
        onSetLobbyStatus(locale.tr("lobby.startFailed", { message: data.errorMessage(error) }), "error");
        dom.setConnection(locale.tr("status.disconnected"), true);
      })
      .finally(() => {
        if (generation !== requestGeneration) return;
        busy = false;
        elements["start-match-button"].disabled = false;
      });
  }

  function returnHome() {
    const snapshot = state.current.snapshot;
    if (busy || !snapshot || !snapshot.outcome) return;
    const generation = ++requestGeneration;
    busy = true;
    dom.setConnection(locale.tr("status.submitting"), false);
    return window.fetch(API.returnHome, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: snapshot.session_id, revision: snapshot.revision }),
    })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return;
        if (payload.arena_redirect) {
          window.location.assign("/arena");
          return;
        }
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode !== "lobby") throw new Error(locale.tr("stateMissing"));
        locale.setLocale(envelope.locale || locale.locale);
        onApplyLocale();
        onClearMatch();
        onSetLobbyFormValues();
        onSetLobbyStatus(locale.tr("lobby.waiting"));
        onRenderLobby();
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation === requestGeneration) dom.showNotice(locale.tr("lobby.returnFailed", { message: data.errorMessage(error) }), "error", 0);
      })
      .finally(() => {
        if (generation === requestGeneration) busy = false;
      });
  }

  function concede() {
    const snapshot = state.current.snapshot;
    const phase = snapshot && snapshot.observation ? String(snapshot.observation.phase || "") : "";
    if (busy || !snapshot || snapshot.outcome || phase === "GAME_OVER") return;
    const generation = ++requestGeneration;
    busy = true;
    setButtonsDisabled(true);
    dom.setConnection(locale.tr("status.submitting"), false);
    return window.fetch(API.concede, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: snapshot.session_id, revision: snapshot.revision }),
    })
      .then(readJsonResponse)
      .then((payload) => {
        if (generation !== requestGeneration) return;
        const envelope = applyServerPayload(payload, { resetSelection: true });
        if (envelope.mode !== "match" || !envelope.snapshot) throw new Error(locale.tr("surrenderMissing"));
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation !== requestGeneration) return;
        let synced = false;
        if (error && error.payload) {
          const envelope = normalizeServerPayload(error.payload);
          if (envelope.mode === "lobby" || envelope.snapshot) {
            applyServerPayload(error.payload, { resetSelection: true });
            synced = true;
          }
        }
        dom.showNotice(locale.tr("surrenderFailed", { message: data.errorMessage(error) }), "error", 0);
        if (error && error.status === 409 && synced) dom.setConnection(locale.tr("status.connected"), false);
        else dom.setConnection(error && error.status ? locale.tr("status.rejected") : locale.tr("status.disconnected"), true);
        if (!synced) loadState(false);
      })
      .finally(() => {
        if (generation !== requestGeneration) return;
        busy = false;
        setButtonsDisabled(false);
        if (state.current.snapshot && state.current.snapshot.outcome && elements["game-over-return"] &&
            !elements["game-over"].hidden) {
          elements["game-over-return"].focus();
        }
      });
  }

  return {
    applyServerPayload,
    applySnapshot,
    concede,
    get busy() { return busy; },
    isBusy: () => busy,
    loadState,
    normalizeServerPayload,
    pollState,
    returnHome,
    startMatch,
    submitAction,
  };
}
