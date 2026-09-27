/** Battlefield feedback and attack guide line. */
export function createFeedback({
  document, window, elements, state, data, dom, translate: tr, statusView, targetIds, renderDecision,
}) {
  let attackPointer = null;
  let attackLine = null;
  let attackStroke = null;

  function publicCharacters(observation) {
    const characters = new Map();
    if (!data.isObject(observation)) return characters;
    [observation.self, observation.opponent].forEach((player) => {
      if (!data.isObject(player)) return;
      [player.hero].concat(data.asArray(player.board)).forEach((card) => {
        const id = data.entityId(card && card.entity_id);
        if (id !== null) characters.set(id, card);
      });
    });
    return characters;
  }

  function publicNode(entityIdValue) {
    const id = data.entityId(entityIdValue);
    if (id === null) return null;
    const selector = `[data-entity-id="${String(id)}"]`;
    return ["self-hero-row", "opponent-hero-row", "self-board", "opponent-board"]
      .map((idName) => elements[idName])
      .map((container) => container && container.querySelector(selector))
      .find(Boolean) || null;
  }

  function initAttackLine() {
    const table = document.querySelector(".table");
    if (!table) return;
    attackLine = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    attackLine.classList.add("attack-line");
    attackLine.setAttribute("aria-hidden", "true");
    attackLine.hidden = true;
    attackStroke = document.createElementNS("http://www.w3.org/2000/svg", "line");
    attackLine.appendChild(attackStroke);
    table.appendChild(attackLine);
    table.addEventListener("pointermove", (event) => {
      const target = event.target instanceof window.Element ? event.target.closest(".targetable") : null;
      attackPointer = { clientX: event.clientX, clientY: event.clientY, target };
      updateAttackLine();
    });
    table.addEventListener("pointerleave", () => {
      attackPointer = null;
      updateAttackLine();
    });
    window.addEventListener("resize", updateAttackLine);
  }

  function updateAttackLine() {
    if (!attackLine || !attackStroke) return;
    const selection = state.current.selection;
    const source = selection.type === "ATTACK" && publicNode(selection.sourceId);
    const table = document.querySelector(".table");
    if (!source || !table || !attackPointer || !table.contains(source)) {
      attackLine.hidden = true;
      return;
    }
    const tableRect = table.getBoundingClientRect();
    const sourceRect = source.getBoundingClientRect();
    let target = attackPointer.target;
    const targetId = target && data.entityId(target.getAttribute("data-entity-id"));
    if (!target || !target.isConnected || !targetIds().has(targetId)) target = null;
    const targetRect = target && target.getBoundingClientRect();
    const x1 = sourceRect.left + sourceRect.width / 2 - tableRect.left;
    const y1 = sourceRect.top + sourceRect.height / 2 - tableRect.top;
    const x2 = targetRect ? targetRect.left + targetRect.width / 2 - tableRect.left : attackPointer.clientX - tableRect.left;
    const y2 = targetRect ? targetRect.top + targetRect.height / 2 - tableRect.top : attackPointer.clientY - tableRect.top;
    attackLine.setAttribute("viewBox", `0 0 ${String(tableRect.width)} ${String(tableRect.height)}`);
    attackStroke.setAttribute("x1", String(x1));
    attackStroke.setAttribute("y1", String(y1));
    attackStroke.setAttribute("x2", String(x2));
    attackStroke.setAttribute("y2", String(y2));
    attackLine.classList.toggle("snapped", Boolean(target));
    attackLine.hidden = false;
  }

  function transientClass(node, className) {
    if (!node) return;
    node.classList.add(className);
    window.setTimeout(() => {
      if (node.isConnected) node.classList.remove(className);
    }, 850);
  }

  function showPublicFeedback(previous, next, previousEventSeq) {
    if (!previous || previous.revision === next.revision) return;
    const oldCharacters = publicCharacters(previous.observation);
    publicCharacters(next.observation).forEach((card, id) => {
      const before = oldCharacters.get(id);
      const node = publicNode(id);
      if (!before) transientClass(node, "summon-flash");
      else if (data.safeNumber(card.health, 0) < data.safeNumber(before.health, 0) || data.safeNumber(card.armor, 0) < data.safeNumber(before.armor, 0)) {
        transientClass(node, "damage-flash");
      } else if (data.safeNumber(card.health, 0) > data.safeNumber(before.health, 0) || data.safeNumber(card.armor, 0) > data.safeNumber(before.armor, 0)) {
        transientClass(node, "heal-flash");
      }
    });
    data.asArray(next.events).forEach((event) => {
      if (event.type === "ATTACK" && data.safeNumber(event.seq, -1) > data.safeNumber(previousEventSeq, -1)) {
        transientClass(publicNode(event.source_entity_id), "attack-source");
        transientClass(publicNode(event.target_entity_id), "attack-target");
      }
    });
  }

  function renderEmptyState() {
    statusView.hideTooltip();
    dom.setText(elements["phase-value"], tr("status.unavailable"));
    dom.setText(elements["turn-value"], tr("status.turn", { value: "—" }));
    dom.setText(elements["active-seat-value"], tr("status.active", { value: "—" }));
    dom.setText(elements["revision-value"], tr("status.revision", { value: "—" }));
    dom.clear(elements["hand"]);
    dom.clear(elements["self-board"]);
    dom.clear(elements["opponent-board"]);
    dom.clear(elements["self-hero-row"]);
    dom.clear(elements["self-hero-status"]);
    const selfPanel = elements["self-hero-row"].closest(".self-panel");
    if (selfPanel) selfPanel.classList.remove("promote-interaction");
    dom.clear(elements["opponent-hero-row"]);
    dom.clear(elements["opponent-hero-status"]);
    dom.clear(elements["self-extras"]);
    dom.clear(elements["opponent-extras"]);
    dom.setHidden(elements["self-hero-status"], true);
    dom.setHidden(elements["opponent-hero-status"], true);
    dom.setHidden(elements["self-extras"], true);
    dom.setHidden(elements["opponent-extras"], true);
    dom.clear(elements["hero-power-row"]);
    dom.clear(elements["event-log"]);
    renderDecision();
    updateAttackLine();
  }

  return { initAttackLine, publicCharacters, publicNode, renderEmptyState, showPublicFeedback, transientClass, updateAttackLine };
}
