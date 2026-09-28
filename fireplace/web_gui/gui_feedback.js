/** Battlefield feedback and attack guide line. */
export function createFeedback({
  document, window, elements, state, data, dom, translate: tr, statusView, targetIds, renderDecision, getBusy,
}) {
  let attackPointer = null;
  let attackLine = null;
  let attackOutline = null;
  let attackStroke = null;
  let attackHead = null;
  let attackOrigin = null;
  let attackGradient = null;
  const svgNamespace = "http://www.w3.org/2000/svg";

  function svgElement(name, className) {
    const node = document.createElementNS(svgNamespace, name);
    if (className) node.classList.add(className);
    return node;
  }

  function setAttackLineVisible(visible) {
    if (!attackLine) return;
    attackLine.toggleAttribute("hidden", !visible);
  }

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
    attackLine = svgElement("svg", "attack-line");
    attackLine.setAttribute("aria-hidden", "true");
    setAttackLineVisible(false);
    const defs = svgElement("defs");
    attackGradient = svgElement("linearGradient");
    attackGradient.id = "attack-guide-gradient";
    attackGradient.setAttribute("gradientUnits", "userSpaceOnUse");
    [["0%", "#b96c36"], ["48%", "#ffe2a0"], ["100%", "#fff4d1"]].forEach(([offset, color]) => {
      const stop = svgElement("stop");
      stop.setAttribute("offset", offset);
      stop.setAttribute("stop-color", color);
      attackGradient.appendChild(stop);
    });
    defs.appendChild(attackGradient);
    attackOutline = svgElement("path", "attack-guide-outline");
    attackStroke = svgElement("path", "attack-guide-stroke");
    attackOrigin = svgElement("circle", "attack-guide-origin");
    attackOrigin.setAttribute("r", "4");
    attackHead = svgElement("path", "attack-guide-head");
    attackLine.append(defs, attackOutline, attackStroke, attackOrigin, attackHead);
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

  function clearAttackLine() {
    attackPointer = null;
    if (!attackLine) return;
    setAttackLineVisible(false);
    attackLine.classList.remove("snapped");
  }

  function updateAttackLine() {
    if (!attackLine || !attackStroke) return;
    const selection = state.current.selection;
    const source = selection.type === "ATTACK" && publicNode(selection.sourceId);
    const table = document.querySelector(".table");
    if (!source || !table || !attackPointer || !table.contains(source) || (getBusy && getBusy())) {
      clearAttackLine();
      return;
    }
    const tableRect = table.getBoundingClientRect();
    const sourceRect = source.getBoundingClientRect();
    let target = attackPointer.target;
    const targetId = target && data.entityId(target.getAttribute("data-entity-id"));
    if (!target || !target.isConnected || !targetIds().has(targetId)) target = null;
    const targetRect = target && target.getBoundingClientRect();
    const sourceCenter = {
      x: sourceRect.left + sourceRect.width / 2 - tableRect.left,
      y: sourceRect.top + sourceRect.height / 2 - tableRect.top,
    };
    const targetCenter = targetRect ? {
      x: targetRect.left + targetRect.width / 2 - tableRect.left,
      y: targetRect.top + targetRect.height / 2 - tableRect.top,
    } : { x: attackPointer.clientX - tableRect.left, y: attackPointer.clientY - tableRect.top };
    const dx = targetCenter.x - sourceCenter.x;
    const dy = targetCenter.y - sourceCenter.y;
    const distance = Math.hypot(dx, dy);
    if (distance < 28) {
      setAttackLineVisible(false);
      return;
    }
    const ux = dx / distance;
    const uy = dy / distance;
    const sourceInset = Math.min(sourceRect.width, sourceRect.height) * .3;
    const targetInset = targetRect ? Math.min(targetRect.width, targetRect.height) * .34 : 0;
    const x1 = sourceCenter.x + ux * sourceInset;
    const y1 = sourceCenter.y + uy * sourceInset;
    const x2 = targetCenter.x - ux * targetInset;
    const y2 = targetCenter.y - uy * targetInset;
    const bend = Math.min(38, distance * .11);
    const controlX = (x1 + x2) / 2 - uy * bend;
    const controlY = (y1 + y2) / 2 + ux * bend;
    const tangentX = x2 - controlX;
    const tangentY = y2 - controlY;
    const tangentLength = Math.hypot(tangentX, tangentY) || 1;
    const tipX = tangentX / tangentLength;
    const tipY = tangentY / tangentLength;
    const baseX = x2 - tipX * 19;
    const baseY = y2 - tipY * 19;
    const path = `M ${x1} ${y1} Q ${controlX} ${controlY} ${x2} ${y2}`;
    attackLine.setAttribute("viewBox", `0 0 ${String(tableRect.width)} ${String(tableRect.height)}`);
    attackGradient.setAttribute("x1", String(x1));
    attackGradient.setAttribute("y1", String(y1));
    attackGradient.setAttribute("x2", String(x2));
    attackGradient.setAttribute("y2", String(y2));
    attackOutline.setAttribute("d", path);
    attackStroke.setAttribute("d", path);
    attackOrigin.setAttribute("cx", String(x1));
    attackOrigin.setAttribute("cy", String(y1));
    attackHead.setAttribute("d", `M ${x2} ${y2} L ${baseX - tipY * 9} ${baseY + tipX * 9} L ${baseX + tipY * 9} ${baseY - tipX * 9} Z`);
    attackLine.classList.toggle("snapped", Boolean(target));
    setAttackLineVisible(true);
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

  return { clearAttackLine, initAttackLine, publicCharacters, publicNode, renderEmptyState, showPublicFeedback, transientClass, updateAttackLine };
}
