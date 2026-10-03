/** Card detail and terminal outcome UI. */
export function createModal({
  elements, state, locale, dom, data, cards, statusView, modifierView,
  findVisibleEntity, publicCharacters,
}) {
  let inspectedCardRef = null;

  function renderOutcome(outcome, phase) {
    const snapshot = state.current.snapshot;
    if (!data.isObject(outcome) || phase !== "GAME_OVER") {
      dom.setHidden(elements["game-over"], true);
      dom.setHidden(elements["terminal-actions"], true);
      return;
    }
    const winner = outcome.winner === null || outcome.winner === undefined ? null : String(outcome.winner);
    const message = winner
      ? (outcome.human_won === true ? locale.tr("outcomeWon") : locale.tr("outcomeLost"))
      : locale.tr("outcomeDraw");
    const winnerLabel = outcome.human_won === true ? winner : outcomeWinnerLabel(winner);
    const suffix = winnerLabel
      ? (locale.locale === "enUS" ? ` (${winnerLabel})` : `（${winnerLabel}）`)
      : "";
    dom.setText(elements["game-over-message"], message + suffix);
    const dismissed = state.current.outcomeDismissedRevision === snapshot.revision;
    dom.setHidden(elements["game-over"], dismissed);
    dom.setHidden(elements["terminal-actions"], !dismissed);
    dom.showNotice(locale.tr("outcomeNotice", { message }), "outcome", 0);
  }

  function outcomeWinnerLabel(winner) {
    if (!winner) return "";
    const policy = String(winner).trim().toLowerCase();
    return ["heuristic", "radical", "mcts"].includes(policy)
      ? locale.tr(`lobby.${policy}`)
      : String(winner);
  }

  function openCardModal(card) {
    if (!data.isObject(card)) return;
    inspectedCardRef = {
      entityId: data.entityId(card.entity_id),
      cardId: data.safeText(card.card_id, ""),
    };
    renderCardModal(card, true);
  }

  function renderCardModal(card, focusClose) {
    if (!data.isObject(card)) return;
    dom.clear(elements["modal-art"]);
    elements["modal-art"].appendChild(cards.createCardArt(card, "render", {
      liveStats: card.printed_cost !== undefined,
    }));
    dom.setText(elements["modal-card-name"], data.cardName(card));
    dom.setText(elements["modal-card-id"], data.safeText(card.card_id, ""));
    dom.clear(elements["modal-stats"]);
    cards.cardStatValues(card).forEach((value) => {
      elements["modal-stats"].appendChild(cards.createStat(value.name, value.label, value.current));
    });
    statusView.renderDetails(elements["modal-statuses"], card, locale.tr);
    dom.setText(elements["modal-card-text"], data.cardText(card) || locale.tr("noCardText"));
    modifierView.renderDetails(elements["modal-modifiers"], card, locale.tr);
    dom.setHidden(elements["card-modal"], false);
    if (focusClose) elements["modal-close"].focus();
  }

  function refreshOpenCardModal() {
    if (!inspectedCardRef || !elements["card-modal"] || elements["card-modal"].hidden) return;
    let card = inspectedCardRef.entityId === null ? null : findVisibleEntity(inspectedCardRef.entityId);
    if (!card && inspectedCardRef.cardId) {
      const snapshot = state.current.snapshot;
      const visible = snapshot && snapshot.observation
        ? publicCharacters(snapshot.observation) : new Map();
      visible.forEach((candidate) => {
        if (!card && candidate.card_id === inspectedCardRef.cardId) card = candidate;
      });
    }
    if (!card) {
      closeCardModal();
      return;
    }
    renderCardModal(card, false);
  }

  function closeCardModal() {
    inspectedCardRef = null;
    dom.setHidden(elements["card-modal"], true);
  }

  return {
    closeCardModal,
    openCardModal,
    refreshOpenCardModal,
    renderCardModal,
    renderOutcome,
    reset() {
      inspectedCardRef = null;
      dom.setHidden(elements["card-modal"], true);
    },
  };
}
