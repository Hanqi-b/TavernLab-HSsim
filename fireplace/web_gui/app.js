import { createLocalization } from "./gui_localization.js";
import { createGuiState } from "./gui_state.js";
import { createDomUtils, createDataUtils } from "./gui_utils.js";
import { createCards } from "./gui_cards.js";
import { createDecisions } from "./gui_decisions.js";
import { createFeedback } from "./gui_feedback.js";
import { createBoard } from "./gui_board.js";
import { createModal } from "./gui_modal.js";
import { createSync } from "./gui_sync.js";
import { createPresentation } from "./gui_presentation.js";
import { createHandDrag } from "./gui_hand_drag.js";
import { createRooms } from "./gui_rooms.js";
import { collectElements, createLobby } from "./gui_core.js";

/**
 * Composition root. Feature modules expose factories and receive only the
 * services they use. The few UI cycles are callback injections kept here so
 * feature modules never import one another in a loop.
 */
function bootstrap() {
  const model = window.FireplaceActionModel;
  if (!model) throw new Error("FireplaceActionModel is unavailable");

  const elements = collectElements(document);
  const locale = createLocalization({
    storageSource: window,
    i18n: window.FireplaceI18n,
  });
  locale.setLocale(locale.readStored("fireplace.locale", "zhCN"));
  const state = createGuiState(model);
  const data = createDataUtils({
    model,
    translate: locale.tr,
    getLocale: () => locale.locale,
  });
  const dom = createDomUtils({
    document,
    window,
    translate: locale.tr,
    elements,
  });

  function renderLlmStatus(snapshot) {
    const statusNode = elements["llm-status"];
    const labelNode = elements["llm-status-label"];
    const modelNode = elements["llm-status-model"];
    const messageNode = elements["llm-status-message"];
    const retryNode = elements["llm-retry"];
    if (!statusNode) return;
    const llm = snapshot && data.isObject(snapshot.llm) ? snapshot.llm : null;
    const llmState = llm && ["idle", "thinking", "error"].includes(String(llm.state).toLowerCase())
      ? String(llm.state).toLowerCase() : null;
    if (!llm || !llmState || !snapshot || snapshot.outcome) {
      dom.setHidden(statusNode, true);
      return;
    }
    const automation = snapshot && data.isObject(snapshot.automation) ? snapshot.automation : null;
    const inferredSeat = llmState === "error"
      ? automation && Number.isInteger(automation.error_seat) ? automation.error_seat : null
      : automation && Number.isInteger(automation.current_seat) ? automation.current_seat : null;
    const seat = Number.isInteger(llm.seat) ? llm.seat : inferredSeat;
    const controller = seat !== null && automation && Array.isArray(automation.controllers)
      ? automation.controllers[seat] : null;
    const configuredModel = controller && controller.model !== null && controller.model !== undefined
      ? data.safeText(controller.model, "") : "";
    const modelName = llm.model === null || llm.model === undefined || llm.model === ""
      ? configuredModel : data.safeText(llm.model, "");
    dom.setHidden(statusNode, false);
    statusNode.className = `llm-status ${llmState}`;
    const stateLabel = locale.tr(`llm.${llmState === "error" ? "errorLabel" : llmState === "thinking" ? "thinking" : "ready"}`);
    const seatLabel = seat === null ? "" : locale.tr("llm.seat", { value: seat + 1 });
    dom.setText(labelNode, [stateLabel, seatLabel].filter(Boolean).join(" · "));
    dom.setText(modelNode, modelName ? locale.tr("llm.model", { value: modelName }) : "");
    if (llmState === "error") {
      dom.setText(messageNode, data.safeText(llm.error, locale.tr("unknownError")));
    } else {
      dom.setText(messageNode, "");
    }
    dom.setHidden(retryNode, llmState !== "error");
    if (retryNode) {
      dom.setText(retryNode, locale.tr("llm.retry"));
      retryNode.setAttribute("aria-label", locale.tr("llm.retry"));
    }
  }

  function renderAutomationStatus(snapshot) {
    const statusNode = elements["automation-status"];
    const modeNode = elements["automation-mode-label"];
    const stateNode = elements["automation-state-label"];
    const seatNode = elements["automation-current-seat"];
    const controllersNode = elements["automation-controllers"];
    const pauseNode = elements["automation-pause"];
    const resumeNode = elements["automation-resume"];
    const stepNode = elements["automation-step"];
    const stopNode = elements["automation-stop"];
    if (!statusNode) return;
    const automation = snapshot && data.isObject(snapshot.automation) ? snapshot.automation : null;
    if (!automation || automation.enabled !== true || snapshot.outcome) {
      dom.setHidden(statusNode, true);
      return;
    }
    const paused = automation.paused === true;
    const pending = automation.pending === true || automation.busy === true;
    const currentSeat = Number.isInteger(automation.current_seat) ? automation.current_seat : null;
    const controllers = Array.isArray(automation.controllers) ? automation.controllers : [];
    statusNode.className = `automation-status${paused ? " paused" : ""}${pending ? " pending" : ""}`;
    dom.setHidden(statusNode, false);
    const codexCodex = snapshot.battle_mode === "codex_codex" ||
      (controllers.length >= 2 && controllers.every((controller) =>
        data.safeText(controller && controller.kind, "").toLowerCase() === "codex"));
    dom.setText(modeNode, locale.tr(codexCodex ? "automation.codexCodexMode" : "automation.mode"));
    dom.setText(stateNode, pending ? locale.tr("automation.pending") :
      (paused ? locale.tr("automation.paused") : locale.tr("automation.running")));
    const currentController = currentSeat !== null && controllers[currentSeat]
      ? controllerLabel(controllers[currentSeat]) : "";
    dom.setText(seatNode, locale.tr("automation.currentSeat", { value: currentController || "—" }));
    if (controllersNode) {
      dom.clear(controllersNode);
      controllers.forEach((controller, index) => {
        const chip = document.createElement("span");
        chip.className = `automation-controller${index === currentSeat ? " current" : ""}`;
        chip.textContent = `${index + 1}: ${controllerLabel(controller)}`;
        controllersNode.appendChild(chip);
      });
    }
    dom.setHidden(pauseNode, paused);
    dom.setHidden(resumeNode, !paused);
    dom.setText(pauseNode, locale.tr("automation.pause"));
    dom.setText(resumeNode, locale.tr("automation.resume"));
    dom.setText(stepNode, locale.tr("automation.step"));
    dom.setText(stopNode, locale.tr("automation.stop"));
    if (pauseNode) pauseNode.disabled = paused;
    if (resumeNode) resumeNode.disabled = !paused;
    if (stepNode) stepNode.disabled = !paused || pending;
    if (stopNode) stopNode.disabled = false;
  }

  function controllerLabel(controller) {
    if (!data.isObject(controller)) return locale.tr("automation.mcts");
    const kind = data.safeText(controller.kind, "mcts").toLowerCase();
    const label = kind === "codex" ? locale.tr("automation.codex") : locale.tr("automation.mcts");
    const model = controller.model === null || controller.model === undefined
      ? "" : data.safeText(controller.model, "");
    return model ? `${label} · ${model}` : label;
  }

  let modal;
  let renderer;
  let sync;
  let lobby;
  let handDrag;
  let feedback;
  let rooms;

  const cards = createCards({
    document,
    window,
    locale,
    translate: locale.tr,
    data,
    isObject: data.isObject,
    safeText: data.safeText,
    cardName: data.cardName,
    cardText: data.cardText,
    entityId: data.entityId,
    onOpenCard: (card) => modal && modal.openCardModal(card),
  });

  const decisions = createDecisions({
    document,
    elements,
    state,
    model,
    data,
    dom,
    locale,
    cards,
    onRender: () => renderer && renderer.renderSnapshot(),
    onSubmitAction: (index) => {
      if (feedback) feedback.clearAttackLine();
      return sync && sync.submitAction(index);
    },
    onLoadState: (silent) => sync && sync.loadState(silent),
    getBusy: () => Boolean(sync && sync.isBusy()),
  });

  feedback = createFeedback({
    document,
    window,
    elements,
    state,
    data,
    dom,
    translate: locale.tr,
    statusView: window.FireplaceStatusView,
    targetIds: () => decisions.targetIds(),
    renderDecision: () => decisions.renderDecision(),
    getBusy: () => Boolean(sync && sync.isBusy()),
  });

  const presentation = createPresentation({
    document, window, elements, data, eventText: decisions.eventText,
  });

  const board = createBoard({
    document,
    elements,
    state,
    model,
    data,
    dom,
    locale,
    cards,
    statusView: window.FireplaceStatusView,
    onChoosePosition: decisions.choosePosition,
    onChooseSource: decisions.chooseSource,
    onChooseTarget: decisions.chooseTarget,
    onToggleMulligan: decisions.toggleMulligan,
    onOpenCard: (card) => modal && modal.openCardModal(card),
    targetIds: decisions.targetIds,
    sourceTypesFor: decisions.sourceTypesFor,
    selectedActions: decisions.selectedActions,
    positionLabel: decisions.positionLabel,
    renderDecision: decisions.renderDecision,
    renderActions: decisions.renderActions,
    renderLog: decisions.renderLog,
    renderOutcome: (outcome, phase) => modal && modal.renderOutcome(outcome, phase),
    updateAttackLine: feedback.updateAttackLine,
  });

  modal = createModal({
    elements,
    state,
    locale,
    dom,
    data,
    cards,
    statusView: window.FireplaceStatusView,
    modifierView: window.FireplaceModifierView,
    findVisibleEntity: decisions.findVisibleEntity,
    publicCharacters: feedback.publicCharacters,
  });

  renderer = {
    renderSnapshot: (withPositionTransition = true) => {
      const previousPositions = withPositionTransition ? presentation.boardPositions() : null;
      board.renderSnapshot();
      if (previousPositions) void presentation.animateBoardReflow(previousPositions);
      renderLlmStatus(state.current.snapshot);
      renderAutomationStatus(state.current.snapshot);
    },
    eventText: decisions.eventText,
    refreshOpenCardModal: modal.refreshOpenCardModal,
  };

  sync = createSync({
    window,
    document,
    elements,
    state,
    locale,
    data,
    dom,
    model,
    cards,
    renderer,
    feedback,
    presentation,
    isDragging: () => Boolean(handDrag && handDrag.isDragging()),
    modal,
    getMode: () => (lobby ? lobby.mode : "lobby"),
    onModeChange: (mode) => lobby && lobby.setScreen(mode),
    onClearMatch: () => {
      presentation.cancel();
      if (handDrag) handDrag.cancel();
      if (lobby) lobby.clearMatchState();
      renderLlmStatus(null);
      renderAutomationStatus(null);
    },
    onApplyLocale: () => {
      if (lobby) lobby.applyLocaleToDocument();
      renderLlmStatus(state.current.snapshot);
      renderAutomationStatus(state.current.snapshot);
      if (rooms) rooms.render();
    },
    onRenderLobby: () => lobby && lobby.renderLobby(),
    onSetLobbyFormValues: () => lobby && lobby.setLobbyFormValues(),
    onSetLobbyStatus: (message, kind) => lobby && lobby.setLobbyStatus(message, kind),
    onRenderLlmStatus: renderLlmStatus,
    onRenderAutomationStatus: renderAutomationStatus,
    onRenderRoom: (payload) => rooms && rooms.renderPayload(payload),
  });

  if (elements["llm-retry"]) {
    elements["llm-retry"].addEventListener("click", () => {
      if (sync) void sync.retryOpponent();
    });
  }

  rooms = createRooms({
    window,
    document,
    elements,
    locale,
    dom,
    data,
    getAccount: () => lobby && lobby.account(),
    getNickname: () => lobby && lobby.nickname(),
    getDeckId: () => lobby && lobby.deckId(),
    getSnapshot: () => state.current.snapshot,
    onPayload: (payload) => sync && sync.applyServerPayload(payload, { resetSelection: true }),
    onSetLobbyStatus: (message, kind) => lobby && lobby.setLobbyStatus(message, kind),
  });

  lobby = createLobby({
    document,
    window,
    elements,
    locale,
    dom,
    state,
    decisions,
    modal,
    onLoadState: (silent) => sync.loadState(silent),
    onPollState: () => (rooms && rooms.isBusy()) ? undefined : sync.pollState(),
    onStartMatch: () => rooms.isRoomMode() ? rooms.create() : sync.startMatch(lobby.nickname()),
    // Room membership is independent from the personal match manager.  Use
    // the room leave endpoint after a terminal room so each account exits its
    // own membership instead of sending the personal /api/return command.
    onReturnHome: () => (rooms && rooms.current ? rooms.leave() : sync.returnHome()),
    onInitAttackLine: feedback.initAttackLine,
    onRenderSnapshot: renderer.renderSnapshot,
    onRenderEmptyState: feedback.renderEmptyState,
    onResetAssets: cards.resetAssets,
    onConcede: () => sync && sync.concede(),
    onAutomation: (command) => sync && sync.automationCommand(command),
    onInitRooms: () => rooms && rooms.init(),
    onRoomModeChange: (mode) => rooms && rooms.setMode(mode),
    getBusy: () => Boolean(sync && sync.isBusy()),
  });

  handDrag = createHandDrag({
    document, window, elements, state, model,
    onSubmitIndex: (index, hint) => sync.submitAction(index, hint),
    onSelectSource: decisions.chooseSource,
    onSelectPosition: decisions.choosePosition,
    onSelectTarget: decisions.chooseTarget,
    getBusy: () => sync.isBusy(),
  });
  handDrag.bind();

  window.addEventListener("resize", cards.refreshLiveStatsOverlays);
  window.addEventListener("beforeunload", cards.resetAssets);
  window.addEventListener("beforeunload", presentation.cancel);
  window.addEventListener("beforeunload", handDrag.cancel);
  lobby.init();

  // Small compatibility surface used by browser acceptance checks.
  window.fireplaceWebGui = {
    loadState: sync.loadState,
    submitAction: sync.submitAction,
    retryOpponent: sync.retryOpponent,
    automationCommand: sync.automationCommand,
    createRoom: rooms.create,
    joinRoom: rooms.join,
    leaveRoom: rooms.leave,
    cancelSelection: decisions.cancelSelection,
    isBusy: () => sync.isBusy() || rooms.isBusy(),
  };
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
