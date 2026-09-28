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

  let modal;
  let renderer;
  let sync;
  let lobby;
  let handDrag;
  let feedback;

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
    },
    onApplyLocale: () => lobby && lobby.applyLocaleToDocument(),
    onRenderLobby: () => lobby && lobby.renderLobby(),
    onSetLobbyFormValues: () => lobby && lobby.setLobbyFormValues(),
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
    onPollState: () => sync.pollState(),
    onStartMatch: () => sync.startMatch(lobby.nickname()),
    onReturnHome: () => sync.returnHome(),
    onInitAttackLine: feedback.initAttackLine,
    onRenderSnapshot: renderer.renderSnapshot,
    onRenderEmptyState: feedback.renderEmptyState,
    onResetAssets: cards.resetAssets,
    onConcede: () => sync && sync.concede(),
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
    cancelSelection: decisions.cancelSelection,
    isBusy: sync.isBusy,
  };
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
