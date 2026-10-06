const API = {
  state: "/api/state",
  action: "/api/action",
  start: "/api/start",
  concede: "/api/concede",
  retryOpponent: "/api/opponent/retry",
  returnHome: "/api/return",
};

/** Owns all HTTP requests, busy state, and revision synchronization. */
export function createSync({
  window, document, elements, state, locale, data, dom, cards,
  renderer, feedback, presentation, isDragging, modal, getMode, onModeChange, onClearMatch,
  onApplyLocale, onRenderLobby, onSetLobbyFormValues, onSetLobbyStatus, onRenderLlmStatus,
  onRenderAutomationStatus, onRenderRoom,
}) {
  let busy = false;
  let retryBusy = false;
  let automationBusy = false;
  let requestGeneration = 0;
  let pollInFlight = false;
  let pollPresentationBusy = false;
  let pollPresentationGeneration = 0;

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

  function normalizeLlm(value) {
    if (!data.isObject(value)) return null;
    const stateValue = data.safeText(value.state, "idle").toLowerCase();
    const llmState = ["idle", "thinking", "error"].includes(stateValue) ? stateValue : "idle";
    return {
      state: llmState,
      model: value.model === null || value.model === undefined || value.model === ""
        ? null : data.safeText(value.model, ""),
      error: value.error === null || value.error === undefined || value.error === ""
        ? null : data.safeText(value.error, ""),
      seat: value.seat === 0 || value.seat === 1 ? value.seat : null,
    };
  }

  function normalizeAutomation(value) {
    if (!data.isObject(value)) return null;
    const rawControllers = Array.isArray(value.controllers) ? value.controllers : [];
    return {
      enabled: value.enabled === true,
      paused: value.paused === true,
      pending: value.pending === true || value.busy === true,
      current_seat: Number.isInteger(value.current_seat) ? value.current_seat : null,
      controllers: rawControllers.map((controller) => {
        if (!data.isObject(controller)) return { kind: "mcts", model: null };
        return {
          kind: data.safeText(controller.kind, "mcts").toLowerCase(),
          model: controller.model === null || controller.model === undefined || controller.model === ""
            ? null : data.safeText(controller.model, ""),
        };
      }),
      error: value.error === null || value.error === undefined || value.error === ""
        ? null : data.safeText(value.error, ""),
      error_seat: value.error_seat === 0 || value.error_seat === 1 ? value.error_seat : null,
    };
  }

  function normalizeRoom(value) {
    if (!data.isObject(value)) return null;
    const status = ["waiting", "playing", "complete"].includes(String(value.status || "").toLowerCase())
      ? String(value.status).toLowerCase() : "waiting";
    const id = data.safeText(value.id || value.room_id || value.roomId, "").trim();
    if (!id) return null;
    const participants = Array.isArray(value.participants)
      ? value.participants.map((participant) => {
        if (!data.isObject(participant)) return null;
        const seat = participant.seat === 0 || participant.seat === 1 ? participant.seat : null;
        const nickname = data.safeText(participant.nickname || participant.name, "").trim();
        return seat === null || !nickname ? null : { seat, nickname };
      }).filter(Boolean)
      : [];
    return {
      id,
      status,
      seat: value.seat === 0 || value.seat === 1 ? value.seat : null,
      participants,
      invite_code: value.invite_code === null || value.invite_code === undefined || value.invite_code === ""
        ? null : data.safeText(value.invite_code, ""),
    };
  }

  function isAutomatedBattleMode(value) {
    return value === "codex_mcts" || value === "codex_codex";
  }

  function snapshotFromPayload(payload) {
    if (!data.isObject(payload)) return null;
    if (data.isObject(payload.snapshot)) {
      const nested = snapshotFromPayload(payload.snapshot);
      if (nested && nested.llm === null && data.isObject(payload.llm)) nested.llm = normalizeLlm(payload.llm);
      if (nested && nested.automation === null && data.isObject(payload.automation)) {
        nested.automation = normalizeAutomation(payload.automation);
      }
      if (nested && !nested.battle_mode && typeof payload.battle_mode === "string") {
        nested.battle_mode = data.safeText(payload.battle_mode, "human");
      }
      if (nested && nested.room === null && data.isObject(payload.room)) {
        nested.room = normalizeRoom(payload.room);
      }
      return nested;
    }
    if (!data.isObject(payload.observation) || !Array.isArray(payload.legal_actions)) return null;
    const automation = normalizeAutomation(payload.automation);
    const automated = Boolean(automation && automation.enabled) || isAutomatedBattleMode(payload.battle_mode);
    return {
      session_id: data.safeText(payload.session_id, ""),
      revision: data.safeNumber(payload.revision, 0),
      observation: payload.observation,
      legal_actions: automated ? [] : payload.legal_actions,
      outcome: payload.outcome === undefined ? null : payload.outcome,
      events: Array.isArray(payload.events) ? payload.events : [],
      llm: normalizeLlm(payload.llm),
      automation,
      battle_mode: typeof payload.battle_mode === "string"
        ? data.safeText(payload.battle_mode, "human") : null,
      room: normalizeRoom(payload.room),
    };
  }

  function normalizeServerPayload(payload) {
    if (!data.isObject(payload)) return { mode: "unknown", locale: locale.locale, snapshot: null };
    const mode = payload.mode === "lobby" ? "lobby" : "match";
    const selectedLocale = locale.normalizeLocale(payload.locale || locale.locale);
    if (mode === "lobby") return { mode, locale: selectedLocale, snapshot: null, raw: payload };
    const source = data.isObject(payload.snapshot) ? payload.snapshot : payload;
    const snapshot = snapshotFromPayload(source);
    if (snapshot && snapshot.room === null && data.isObject(payload.room)) {
      snapshot.room = normalizeRoom(payload.room);
    }
    return { mode, locale: selectedLocale, snapshot, raw: payload };
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
      if (typeof onRenderRoom === "function") onRenderRoom(payload);
      locale.setLocale(envelope.locale || locale.locale);
      onApplyLocale();
      onRenderLobby();
      return envelope;
    }
    if (!envelope.snapshot) throw new Error(locale.tr("stateMissing"));
    if (getMode() !== "match") onClearMatch();
    if (typeof onRenderRoom === "function") onRenderRoom(payload);
    locale.setLocale(envelope.locale || locale.locale);
    onApplyLocale();
    if (state.isStale(envelope.snapshot)) return envelope;
    applySnapshot(envelope.snapshot, options || { resetSelection: state.isDecisionChanged(envelope.snapshot) });
    onModeChange("match");
    return envelope;
  }

  function loadState(silent = false) {
    if (pollInFlight) return Promise.resolve(null);
    pollInFlight = true;
    const generation = requestGeneration;
    if (!silent) dom.setConnection(locale.tr("status.reading"), false);
    return window.fetch(API.state, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(readJsonResponse)
      .then(async (payload) => {
        if (generation !== requestGeneration || busy || automationBusy || (isDragging && isDragging())) return null;
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode === "match" && envelope.snapshot) {
          await reconcileMatchPayload(payload, generation, {
            animate: false,
            resetSelection: state.isDecisionChanged(envelope.snapshot),
          });
        } else {
          applyServerPayload(payload, { resetSelection: false });
        }
        dom.setConnection(locale.tr("status.connected"), false);
        return envelope.snapshot;
      })
      .catch((error) => {
        if (generation !== requestGeneration) return null;
        dom.setConnection(locale.tr("status.disconnected"), true);
        if (!silent || (!state.current.snapshot && getMode() !== "lobby")) {
          dom.showNotice(locale.tr("stateUnavailable", { message: data.errorMessage(error) }), "error", 0);
          if (!state.current.snapshot) onRenderLobby();
        }
        return null;
      })
      .finally(() => { pollInFlight = false; });
  }

  function pollState() {
    if (busy || retryBusy || automationBusy || pollInFlight || pollPresentationBusy) return;
    pollInFlight = true;
    const generation = requestGeneration;
    return window.fetch(API.state, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(readJsonResponse)
      .then(async (payload) => {
        if (generation !== requestGeneration || busy || retryBusy || automationBusy || (isDragging && isDragging())) return;
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode === "lobby") {
          applyServerPayload(payload, { resetSelection: getMode() !== "lobby" });
          dom.setConnection(locale.tr("status.connected"), false);
          return;
        }
        const next = envelope.snapshot;
        if (!next || state.isStale(next)) return;
        dom.setConnection(locale.tr("status.connected"), false);
        if (dataFingerprint(next) !== state.current.fingerprint ||
            (state.current.snapshot && next.revision > state.current.snapshot.revision)) {
          await reconcileMatchPayload(payload, generation, {
            animate: true,
            resetSelection: false,
            showDecisionNotice: true,
          });
        }
      })
      .catch(() => {
        if (generation === requestGeneration) dom.setConnection(locale.tr("status.disconnected"), true);
      })
      .finally(() => { pollInFlight = false; });
  }

  function dataFingerprint(value) {
    try { return JSON.stringify(value); } catch (_error) { return String(Date.now()); }
  }

  function presentationSteps(payload, current, next) {
    if (!data.isObject(payload) || !Array.isArray(payload.presentation_steps) || !next) return [];
    const currentRevision = current ? data.safeNumber(current.revision, 0) : -1;
    const nextRevision = data.safeNumber(next.revision, 0);
    const sessionId = next.session_id;
    const byRevision = new Map();
    payload.presentation_steps.forEach((frame) => {
      if (!data.isObject(frame)) return;
      const frameRevision = data.safeNumber(frame.revision, -1);
      if (frameRevision <= currentRevision || frameRevision > nextRevision) return;
      if (frame.session_id !== undefined && data.safeText(frame.session_id, "") !== sessionId) return;
      if (!data.isObject(frame.observation)) return;
      if (!byRevision.has(frameRevision)) byRevision.set(frameRevision, frame);
    });
    return [...byRevision.entries()]
      .sort(([left], [right]) => left - right)
      .map(([, frame]) => frame);
  }

  function presentationHasGap(steps, current, next) {
    if (!current || !next || !steps.length) return true;
    const firstRevision = data.safeNumber(current.revision, 0) + 1;
    const finalRevision = data.safeNumber(next.revision, 0);
    const revisions = new Set(steps.map((frame) => data.safeNumber(frame.revision, -1)));
    for (let revision = firstRevision; revision <= finalRevision; revision += 1) {
      if (!revisions.has(revision)) return true;
    }
    return false;
  }

  async function reconcileMatchPayload(payload, generation, {
    animate = true,
    resetSelection = true,
    showDecisionNotice = false,
  } = {}) {
    const envelope = normalizeServerPayload(payload);
    if (envelope.mode !== "match" || !envelope.snapshot) throw new Error(locale.tr("stateMissing"));
    const next = envelope.snapshot;
    const current = state.current.snapshot;
    if (generation !== requestGeneration) return envelope;
    if (!current || current.session_id !== next.session_id || state.isStale(next) ||
        next.revision <= current.revision) {
      if (!current || !state.isStale(next) && dataFingerprint(next) !== state.current.fingerprint) {
        applyServerPayload(payload, { resetSelection });
      }
      return envelope;
    }

    const steps = presentationSteps(payload, current, next);
    const canAnimate = animate && steps.length > 0 && !presentationHasGap(steps, current, next) &&
      !pollPresentationBusy && current.session_id === next.session_id;
    if (!canAnimate) {
      const hadSnapshot = Boolean(current);
      const decisionChanged = state.isDecisionChanged(next);
      applyServerPayload(payload, { resetSelection: resetSelection || decisionChanged });
      if (showDecisionNotice && decisionChanged && hadSnapshot && !busy) {
        dom.showNotice(locale.tr("stateUpdated"), "", 3200);
      }
      return envelope;
    }

    pollPresentationBusy = true;
    const presentationToken = ++pollPresentationGeneration;
    try {
      await presentation.play(steps, next, {
        current: () => state.current.snapshot,
        commit: (frame, isFinal = false) => {
          const normalizedFrame = {
            ...frame,
            session_id: frame.session_id || next.session_id,
            llm: frame.llm === undefined
              ? (state.current.snapshot && state.current.snapshot.llm) || null
              : normalizeLlm(frame.llm),
            room: frame.room === undefined
              ? (state.current.snapshot && state.current.snapshot.room) || next.room || null
              : normalizeRoom(frame.room),
          };
          applySnapshot(normalizedFrame, {
            resetSelection: true,
            positionTransition: false,
            visualFeedbackDisabled: true,
          });
        },
      }, () => generation === requestGeneration && presentationToken === pollPresentationGeneration,
      { maxPlaybackMs: 20000 });
      if (generation === requestGeneration && presentationToken === pollPresentationGeneration &&
          state.current.snapshot && state.current.snapshot.session_id === next.session_id &&
          state.current.snapshot.revision < next.revision) {
        // A cancelled/shortened presentation must still converge to the
        // authoritative latest state so a bounded step window cannot strand
        // the browser at an old revision.
        applyServerPayload(payload, { resetSelection: true });
      }
    } catch (error) {
      if (generation === requestGeneration && presentationToken === pollPresentationGeneration) {
        presentation.cancel();
        applyServerPayload(payload, { resetSelection: true });
        window.console.error("Opponent presentation failed", error);
      }
    } finally {
      if (presentationToken === pollPresentationGeneration) pollPresentationBusy = false;
    }
    return envelope;
  }

  function applySnapshot(next, options = {}) {
    if (data.isObject(next)) {
      const hasLlm = Object.prototype.hasOwnProperty.call(next, "llm");
      const hasAutomation = Object.prototype.hasOwnProperty.call(next, "automation");
      const hasBattleMode = Object.prototype.hasOwnProperty.call(next, "battle_mode");
      const hasRoom = Object.prototype.hasOwnProperty.call(next, "room");
      next = {
        ...next,
        llm: hasLlm ? normalizeLlm(next.llm) : ((state.current.snapshot && state.current.snapshot.llm) || null),
        automation: hasAutomation ? normalizeAutomation(next.automation) :
          ((state.current.snapshot && state.current.snapshot.automation) || null),
        battle_mode: hasBattleMode ? data.safeText(next.battle_mode, "human") :
          ((state.current.snapshot && state.current.snapshot.battle_mode) || null),
        room: hasRoom ? normalizeRoom(next.room) :
          ((state.current.snapshot && state.current.snapshot.room) || null),
      };
    }
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
    renderer.renderSnapshot(options.positionTransition !== false);
    if (typeof onRenderLlmStatus === "function") onRenderLlmStatus(next);
    if (typeof onRenderAutomationStatus === "function") onRenderAutomationStatus(next);
    modal.refreshOpenCardModal();
    if (!options.visualFeedbackDisabled) feedback.showPublicFeedback(previous, next, previousEventSeq);
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

  function setOpponentDisabled(disabled) {
    const select = elements["opponent-select"] || document.getElementById("opponent-select");
    if (select) select.disabled = Boolean(disabled);
  }

  function setBattleModeDisabled(disabled) {
    ["battle-mode-select", "codex-model-input", "codex-self-model-input", "codex-opponent-model-input"]
      .forEach((id) => {
        const input = elements[id] || document.getElementById(id);
        if (input) input.disabled = Boolean(disabled);
      });
  }

  function submitAction(index, presentationHint = null) {
    const snapshot = state.current.snapshot;
    const action = state.current.actionIndex.actions[index];
    if (busy || !snapshot || ((isDragging && isDragging()) &&
        !(presentationHint && presentationHint.preanimatedPlay))) return;
    if (!data.isObject(action)) {
      dom.showNotice(locale.tr("staleRevision"), "error", 0);
      loadState(false);
      return;
    }
    const generation = ++requestGeneration;
    busy = true;
    setButtonsDisabled(true);
    dom.setConnection(locale.tr("status.submitting"), false);
    return window.fetch(API.action, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: snapshot.session_id, revision: snapshot.revision, action }),
    })
      .then(readJsonResponse)
      .then(async (payload) => {
        if (generation !== requestGeneration) return;
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode !== "match" || !envelope.snapshot) throw new Error(locale.tr("actionMissing"));
        const steps = Array.isArray(payload.presentation_steps) ? payload.presentation_steps : [];
        const last = steps[steps.length - 1];
        const before = state.current.snapshot;
        if (before && steps.length && last && last.revision <= envelope.snapshot.revision &&
            steps[0].revision > before.revision && before.session_id === envelope.snapshot.session_id) {
          try {
            await presentation.play(steps, envelope.snapshot, {
              current: () => state.current.snapshot,
              commit: (next, isFinal = false) => {
                applySnapshot(next, {
                  resetSelection: true, positionTransition: false, visualFeedbackDisabled: true,
                });
                setButtonsDisabled(!isFinal);
              },
            }, () => generation === requestGeneration, {
              skipFirstIntent: Boolean(presentationHint && presentationHint.preanimatedPlay),
              beforeFinal: () => { busy = false; },
            });
          } catch (animationError) {
            presentation.cancel();
            applyServerPayload(payload, { resetSelection: true });
            window.console.error("Action presentation failed", animationError);
          }
        } else {
          applyServerPayload(payload, { resetSelection: true });
        }
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
        if (!synced) window.setTimeout(() => loadState(false), 0);
      })
      .finally(() => {
        if (generation !== requestGeneration) return;
        busy = false;
        setButtonsDisabled(false);
      });
  }

  function startMatch(nickname, opponent) {
    if (busy) return;
    if (!nickname) return;
    const generation = ++requestGeneration;
    busy = true;
    elements["start-match-button"].disabled = true;
    setOpponentDisabled(true);
    setBattleModeDisabled(true);
    onSetLobbyStatus(locale.tr("lobby.starting"));
    dom.setConnection(locale.tr("status.connecting"), false);
    const selectedDeck = document.getElementById("deck-select");
    const deckId = selectedDeck && typeof selectedDeck.value === "string"
      ? selectedDeck.value.trim()
      : "";
    const selectedOpponent = typeof opponent === "string" && opponent.trim()
      ? opponent.trim()
      : (document.getElementById("opponent-select")?.value || "mcts");
    const selectedBattleMode = document.getElementById("battle-mode-select")?.value || "human";
    const body = { nickname, locale: locale.locale };
    // A deck identifier is sent only when the user explicitly chose a saved deck.
    if (deckId) body.deck_id = deckId;
    if (selectedBattleMode === "codex_mcts" || selectedBattleMode === "codex_codex") {
      body.battle_mode = selectedBattleMode;
      const modelInput = document.getElementById("codex-self-model-input");
      const codexModel = modelInput && typeof modelInput.value === "string"
        ? modelInput.value.trim()
        : "";
      if (codexModel) body.codex_self_model = codexModel;
      if (selectedBattleMode === "codex_codex") {
        const opponentModelInput = document.getElementById("codex-opponent-model-input");
        const opponentModel = opponentModelInput && typeof opponentModelInput.value === "string"
          ? opponentModelInput.value.trim()
          : "";
        if (opponentModel) body.codex_model = opponentModel;
      }
    } else {
      body.opponent = selectedOpponent;
    }
    if (selectedBattleMode === "human" && selectedOpponent === "codex") {
      const modelInput = document.getElementById("codex-model-input");
      const codexModel = modelInput && typeof modelInput.value === "string"
        ? modelInput.value.trim()
        : "";
      if (codexModel) body.codex_model = codexModel;
    }
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
        setOpponentDisabled(false);
        setBattleModeDisabled(false);
      });
  }

  function retryOpponent() {
    const snapshot = state.current.snapshot;
    const llm = snapshot && snapshot.llm;
    if (busy || retryBusy || !snapshot || snapshot.outcome || !llm || llm.state !== "error") return;
    const generation = ++requestGeneration;
    retryBusy = true;
    if (elements["llm-retry"]) elements["llm-retry"].disabled = true;
    return window.fetch(API.retryOpponent, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: snapshot.session_id, revision: snapshot.revision }),
    })
      .then(readJsonResponse)
      .then(async (payload) => {
        if (generation !== requestGeneration) return;
        await reconcileMatchPayload(payload, generation, {
          animate: true,
          resetSelection: true,
        });
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation !== requestGeneration) return;
        if (error && error.payload) {
          const envelope = normalizeServerPayload(error.payload);
          if (envelope.mode === "match" && envelope.snapshot) {
            applyServerPayload(error.payload, { resetSelection: true });
          }
        }
        dom.showNotice(locale.tr("submitFailed", { message: data.errorMessage(error) }), "error", 0);
        dom.setConnection(error && error.status ? locale.tr("status.rejected") : locale.tr("status.disconnected"), true);
      })
      .finally(() => {
        retryBusy = false;
        if (elements["llm-retry"]) elements["llm-retry"].disabled = false;
        if (typeof onRenderLlmStatus === "function" && state.current.snapshot) {
          onRenderLlmStatus(state.current.snapshot);
        }
      });
  }

  function setAutomationButtonsDisabled(disabled) {
    ["automation-pause", "automation-resume", "automation-step", "automation-stop"]
      .forEach((id) => {
        if (elements[id]) elements[id].disabled = Boolean(disabled);
      });
  }

  function automationCommand(command) {
    const snapshot = state.current.snapshot;
    const automation = snapshot && snapshot.automation;
    const action = typeof command === "string" ? command.trim().toLowerCase() : "";
    if (automationBusy || !snapshot || snapshot.outcome || !automation || automation.enabled !== true) return;
    if (!["pause", "resume", "step", "stop"].includes(action)) return;
    if (action === "pause" && automation.paused) return;
    if (action === "resume" && !automation.paused) return;
    if (action === "step" && (!automation.paused || automation.pending)) return;
    const generation = ++requestGeneration;
    automationBusy = true;
    setAutomationButtonsDisabled(true);
    dom.setConnection(locale.tr("status.submitting"), false);
    return window.fetch("/api/automation", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ command: action, session_id: snapshot.session_id, revision: snapshot.revision }),
    })
      .then(readJsonResponse)
      .then(async (payload) => {
        if (generation !== requestGeneration) return;
        const envelope = normalizeServerPayload(payload);
        if (envelope.mode === "lobby") {
          applyServerPayload(payload, { resetSelection: false });
        } else {
          await reconcileMatchPayload(payload, generation, {
            animate: action === "step",
            resetSelection: true,
          });
        }
        dom.setConnection(locale.tr("status.connected"), false);
      })
      .catch((error) => {
        if (generation !== requestGeneration) return;
        if (error && error.payload) {
          const envelope = normalizeServerPayload(error.payload);
          if (envelope.mode === "lobby" || envelope.snapshot) {
            applyServerPayload(error.payload, { resetSelection: true });
          }
        }
        const key = `automation.${action}Failed`;
        dom.showNotice(locale.tr(key, { message: data.errorMessage(error) }), "error", 0);
        dom.setConnection(error && error.status ? locale.tr("status.rejected") : locale.tr("status.disconnected"), true);
      })
      .finally(() => {
        automationBusy = false;
        setAutomationButtonsDisabled(false);
        if (typeof onRenderAutomationStatus === "function" && state.current.snapshot) {
          onRenderAutomationStatus(state.current.snapshot);
        }
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
    if (busy || (isDragging && isDragging()) || !snapshot || snapshot.outcome || phase === "GAME_OVER") return;
    const generation = ++requestGeneration;
    busy = true;
    setButtonsDisabled(true);
    dom.setConnection(locale.tr("status.submitting"), false);
    function sendConcede(requestSnapshot, canRetry) {
      return window.fetch(API.concede, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: requestSnapshot.session_id, revision: requestSnapshot.revision }),
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
          let syncedSnapshot = null;
          if (error && error.payload) {
            const envelope = normalizeServerPayload(error.payload);
            if (envelope.mode === "lobby" || envelope.snapshot) {
              applyServerPayload(error.payload, { resetSelection: true });
              synced = true;
              syncedSnapshot = envelope.snapshot;
            }
          }
          // A Codex action may finish between reading the browser revision and
          // accepting surrender. Reconcile the authoritative 409 payload once
          // and retry with that revision while preserving the user's decision.
          if (canRetry && error && error.status === 409 && synced && syncedSnapshot &&
              syncedSnapshot.session_id === requestSnapshot.session_id && !syncedSnapshot.outcome) {
            return sendConcede(state.current.snapshot || syncedSnapshot, false);
          }
          dom.showNotice(locale.tr("surrenderFailed", { message: data.errorMessage(error) }), "error", 0);
          if (error && error.status === 409 && synced) dom.setConnection(locale.tr("status.connected"), false);
          else dom.setConnection(error && error.status ? locale.tr("status.rejected") : locale.tr("status.disconnected"), true);
          if (!synced) window.setTimeout(() => loadState(false), 0);
        });
    }
    return sendConcede(snapshot, true)
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
    isBusy: () => busy || Boolean(isDragging && isDragging()),
    loadState,
    normalizeServerPayload,
    pollState,
    automationCommand,
    retryOpponent,
    returnHome,
    startMatch,
    submitAction,
  };
}
