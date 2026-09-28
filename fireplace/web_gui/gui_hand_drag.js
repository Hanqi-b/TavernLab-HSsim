/**
 * Pointer drag presentation for cards in the player's hand.
 *
 * This module only reads the server supplied legal action list.  It never
 * decides whether a card is playable or invents a board rule: every drop is
 * resolved to one of the current PLAY_CARD actions before it is submitted.
 */
export function createHandDrag({
  document,
  window,
  elements,
  state,
  model,
  onSubmitIndex,
  onSelectSource,
  onSelectPosition,
  onSelectTarget,
  getBusy,
}) {
  const hand = elements && (elements.hand || elements["hand"]);
  const board = elements && (elements["self-board"] || elements.selfBoard);
  const targetRoots = [
    hand,
    board,
    elements && elements["opponent-board"],
    elements && elements["self-hero-row"],
    elements && elements["opponent-hero-row"],
  ].filter(Boolean);

  const distanceThreshold = 7;
  const animationDuration = 280;
  const returnDuration = 210;
  const markers = [];
  const highlighted = new Set();
  let active = null;
  let bound = false;
  let suppressClickCard = null;
  let suppressClickTimer = null;

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function sameId(left, right) {
    if (model && typeof model.sameId === "function") {
      return model.sameId(left, right);
    }
    if (left === null || left === undefined || right === null || right === undefined) {
      return false;
    }
    return String(left) === String(right);
  }

  function entityId(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = typeof value === "number" ? value : Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function nodeEntityId(node) {
    if (!node || typeof node.getAttribute !== "function") return null;
    return entityId(node.getAttribute("data-entity-id"));
  }

  function currentActions() {
    const current = state && state.current;
    return asArray(current && current.actionIndex && current.actionIndex.actions);
  }

  function hasField(action, field) {
    return isObject(action) && action[field] !== undefined && action[field] !== null;
  }

  function playActionsFor(sourceId) {
    return currentActions().filter((action) => isObject(action) &&
      action.type === "PLAY_CARD" && sameId(action.source_entity_id, sourceId));
  }

  function sourceCardForEvent(event) {
    if (!hand || !event || !event.target) return null;
    const target = asElement(event.target);
    if (!target || (target.closest && target.closest(".card-inspect"))) return null;
    const card = target.closest ? target.closest(".hand-card.playable") : null;
    if (!card || !hand.contains(card)) return null;
    return card;
  }

  function asElement(value) {
    if (!value) return null;
    if (value.nodeType === 1) return value;
    return value.parentElement || null;
  }

  function pointFromEvent(event) {
    return { x: Number(event.clientX) || 0, y: Number(event.clientY) || 0 };
  }

  function rectCenter(rect) {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  function pointInRect(point, rect) {
    return Boolean(rect && point.x >= rect.left && point.x <= rect.right &&
      point.y >= rect.top && point.y <= rect.bottom);
  }

  function distanceSquared(left, right) {
    const dx = left.x - right.x;
    const dy = left.y - right.y;
    return dx * dx + dy * dy;
  }

  function uniqueFieldValues(actions, field) {
    const values = [];
    actions.forEach((action) => {
      if (!hasField(action, field)) return;
      const value = field === "position" ? Number(action[field]) : entityId(action[field]);
      if (field === "position" && !Number.isFinite(value)) return;
      if (field !== "position" && value === null) return;
      if (!values.some((entry) => field === "position" ? entry === value : sameId(entry, value))) {
        values.push(value);
      }
    });
    return values;
  }

  function actionKey(action) {
    if (model && typeof model.actionKey === "function") return model.actionKey(action);
    return [
      action && action.type,
      action && action.source_entity_id,
      action && action.target_entity_id,
      action && action.choose_option_entity_id,
      action && action.position,
    ].join("|");
  }

  function uniqueAction(actions) {
    const list = asArray(actions).filter(isObject);
    if (list.length === 1) return list[0];
    if (!list.length) return null;
    const keys = new Set(list.map(actionKey));
    return keys.size === 1 ? list[0] : null;
  }

  function actionIndex(action) {
    if (!action) return -1;
    const actions = currentActions();
    const direct = actions.indexOf(action);
    if (direct >= 0) return direct;
    const key = actionKey(action);
    return actions.findIndex((candidate) => actionKey(candidate) === key);
  }

  function actionNeedsBranch(action) {
    return hasField(action, "choose_option_entity_id");
  }

  function actionNeedsTarget(action) {
    return hasField(action, "target_entity_id");
  }

  function actionNeedsPosition(action) {
    return hasField(action, "position");
  }

  function clearHighlights() {
    highlighted.forEach((node) => {
      node.classList.remove("hand-drag-target", "hand-drag-hover");
    });
    highlighted.clear();
    markers.splice(0).forEach((marker) => marker.remove());
    if (board) board.classList.remove("hand-drag-board");
    if (hand) hand.classList.remove("hand-drag-active");
  }

  function visibleEntityNodes() {
    const result = [];
    const seen = new Set();
    targetRoots.forEach((root) => {
      if (!root || typeof root.querySelectorAll !== "function") return;
      root.querySelectorAll("[data-entity-id]").forEach((node) => {
        if (!seen.has(node)) {
          seen.add(node);
          result.push(node);
        }
      });
    });
    return result;
  }

  function positionCenter(position) {
    if (!board) return null;
    const slot = Array.from(board.querySelectorAll("[data-position]")).find((node) => {
      return Number(node.getAttribute("data-position")) === Number(position);
    });
    if (slot) return rectCenter(slot.getBoundingClientRect());

    const boardRect = board.getBoundingClientRect();
    const cards = Array.from(board.querySelectorAll(".board-card"));
    if (!cards.length) return rectCenter(boardRect);
    const cardRects = cards.map((node) => node.getBoundingClientRect());
    const count = cardRects.length + 1;
    const minWidth = parseFloat(window.getComputedStyle(cards[0]).minWidth) || 52;
    const oldWidth = board.querySelector(".board-slot") ? 96 : cardRects[0].width;
    const width = Math.max(minWidth, Math.min(oldWidth, boardRect.width / count));
    const numericPosition = Math.max(0, Math.min(cardRects.length, Number(position) || 0));
    const x = boardRect.left + (boardRect.width - width * count) / 2 +
      width * (numericPosition + .5);
    const y = cardRects.reduce((total, rect) => total + rect.top + rect.height / 2, 0) / cardRects.length;
    return { x, y };
  }

  function refreshPositionMarkers(drag) {
    if (!drag || !drag.positions) return;
    drag.positions.forEach((entry) => {
      const center = positionCenter(entry.value);
      if (!center) return;
      entry.center = center;
      const marker = entry.marker;
      const width = marker.offsetWidth || 54;
      const height = marker.offsetHeight || 78;
      marker.style.left = `${center.x - width / 2}px`;
      marker.style.top = `${center.y - height / 2}px`;
    });
  }

  function createPositionMarkers(drag, positions) {
    if (!positions.length || !document || !document.body) return;
    if (board) board.classList.add("hand-drag-board");
    drag.positions = positions.map((value) => {
      const marker = document.createElement("span");
      marker.className = "hand-drag-position-marker hand-drag-available";
      marker.setAttribute("aria-hidden", "true");
      marker.dataset.position = String(value);
      document.body.appendChild(marker);
      markers.push(marker);
      return { value, marker, center: null };
    });
    refreshPositionMarkers(drag);
  }

  function prepareDropFeedback(drag) {
    clearHighlights();
    if (hand) hand.classList.add("hand-drag-active");
    const targetIds = uniqueFieldValues(drag.candidates, "target_entity_id");
    if (targetIds.length) {
      visibleEntityNodes().forEach((node) => {
        if (node === drag.card) return;
        const id = nodeEntityId(node);
        if (targetIds.some((targetId) => sameId(targetId, id))) {
          node.classList.add("hand-drag-target");
          highlighted.add(node);
        }
      });
    }
    if (board && drag.candidates.some((action) => !actionNeedsTarget(action) && !actionNeedsPosition(action))) {
      board.classList.add("hand-drag-board");
    }
    createPositionMarkers(drag, uniqueFieldValues(drag.candidates, "position"));
  }

  function targetNodeAt(point, drag) {
    let element = null;
    if (document && typeof document.elementFromPoint === "function") {
      element = document.elementFromPoint(point.x, point.y);
    }
    const node = asElement(element);
    const candidate = node && node.closest ? node.closest("[data-entity-id]") : null;
    if (!candidate || candidate === drag.card || !highlighted.has(candidate)) return null;
    return candidate;
  }

  function nearestPosition(point, drag) {
    if (!drag || !drag.positions || !drag.positions.length) return null;
    if (board && !pointInRect(point, board.getBoundingClientRect())) return null;
    refreshPositionMarkers(drag);
    return drag.positions.reduce((nearest, entry) => {
      if (!entry.center) return nearest;
      if (!nearest || distanceSquared(point, entry.center) < distanceSquared(point, nearest.center)) {
        return entry;
      }
      return nearest;
    }, null);
  }

  function hasBoardDrop(candidates) {
    // A branch-only PLAY_CARD still has a meaningful board drop: the source
    // selection opens the existing branch chooser after the card lands.
    return candidates.some((action) => !actionNeedsTarget(action) && !actionNeedsPosition(action));
  }

  function resolveDrop(drag, event) {
    const point = pointFromEvent(event);
    const targetNode = targetNodeAt(point, drag);
    if (targetNode) {
      const targetId = nodeEntityId(targetNode);
      const candidates = drag.candidates.filter((action) => hasField(action, "target_entity_id") &&
        sameId(action.target_entity_id, targetId));
      if (candidates.length) {
        return {
          kind: "target",
          targetId,
          action: uniqueAction(candidates),
          candidates,
          destination: rectCenter(targetNode.getBoundingClientRect()),
        };
      }
    }

    const position = nearestPosition(point, drag);
    if (position) {
      const candidates = drag.candidates.filter((action) => hasField(action, "position") &&
        Number(action.position) === Number(position.value));
      if (candidates.length) {
        return {
          kind: "position",
          position: position.value,
          action: uniqueAction(candidates),
          candidates,
          destination: position.center,
        };
      }
    }

    if (board && pointInRect(point, board.getBoundingClientRect()) && hasBoardDrop(drag.candidates)) {
      const candidates = drag.candidates.filter((action) => !actionNeedsTarget(action) &&
        !actionNeedsPosition(action));
      return {
        kind: "board",
        action: uniqueAction(candidates),
        candidates,
        destination: rectCenter(board.getBoundingClientRect()),
      };
    }
    return null;
  }

  function updateHover(drag, event) {
    if (!drag || !drag.dragging) return;
    highlighted.forEach((node) => node.classList.remove("hand-drag-hover"));
    markers.forEach((marker) => marker.classList.remove("hand-drag-hover"));
    const point = pointFromEvent(event);
    const target = targetNodeAt(point, drag);
    if (target) {
      target.classList.add("hand-drag-hover");
      drag.hover = { kind: "target", node: target };
      return;
    }
    const position = nearestPosition(point, drag);
    if (position) {
      position.marker.classList.add("hand-drag-hover");
      drag.hover = { kind: "position", entry: position };
      return;
    }
    drag.hover = null;
  }

  function createGhost(drag) {
    if (!document || !document.body || !drag.card) return null;
    const clone = drag.card.cloneNode(true);
    clone.classList.add("hand-drag-ghost");
    clone.setAttribute("aria-hidden", "true");
    clone.removeAttribute("id");
    clone.removeAttribute("tabindex");
    clone.removeAttribute("data-entity-id");
    clone.removeAttribute("data-testid");
    clone.querySelectorAll("[id]").forEach((node) => node.removeAttribute("id"));
    const rect = drag.originRect;
    Object.assign(clone.style, {
      position: "fixed",
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width || 100}px`,
      height: `${rect.height || 140}px`,
      margin: "0",
      transform: "translate3d(0, 0, 0) rotate(0deg) scale(1)",
      pointerEvents: "none",
      zIndex: "1001",
    });
    document.body.appendChild(clone);
    return clone;
  }

  function moveGhost(drag, event) {
    if (!drag || !drag.ghost) return;
    const point = pointFromEvent(event);
    const dx = point.x - drag.startPoint.x;
    const dy = point.y - drag.startPoint.y;
    drag.offset = { x: dx, y: dy };
    drag.ghost.style.transform = `translate3d(${dx}px, ${dy}px, 0) rotate(${Math.max(-3, Math.min(3, dx / 22))}deg) scale(1.03)`;
  }

  function reducedMotion() {
    if (!window || typeof window.matchMedia !== "function") return false;
    try { return Boolean(window.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (_error) { return false; }
  }

  function waitForAnimation(drag, keyframes, duration, easing) {
    if (!drag || !drag.ghost || drag.cancelled) return Promise.resolve();
    const ms = reducedMotion() ? 1 : duration;
    if (typeof drag.ghost.animate === "function") {
      const animation = drag.ghost.animate(keyframes, {
        duration: ms,
        easing,
        fill: "forwards",
      });
      drag.animation = animation;
      return Promise.resolve(animation.finished).catch(() => {});
    }
    const last = keyframes[keyframes.length - 1];
    if (last && last.transform) drag.ghost.style.transform = last.transform;
    return new Promise((resolve) => {
      const setTimer = window && typeof window.setTimeout === "function" ? window.setTimeout.bind(window) : setTimeout;
      drag.timer = setTimer(resolve, ms + 24);
    });
  }

  function ghostTransform(drag, point, scale) {
    const dx = point.x - drag.originRect.left;
    const dy = point.y - drag.originRect.top;
    return `translate3d(${dx}px, ${dy}px, 0) rotate(0deg) scale(${scale})`;
  }

  function releasePointer(drag) {
    if (!drag || !drag.card || drag.pointerId === undefined) return;
    if (typeof drag.card.hasPointerCapture === "function" && drag.card.hasPointerCapture(drag.pointerId) &&
        typeof drag.card.releasePointerCapture === "function") {
      try { drag.card.releasePointerCapture(drag.pointerId); } catch (_error) { /* already released */ }
    }
  }

  function cleanupDrag(drag) {
    if (!drag) return;
    if (drag.animation && typeof drag.animation.cancel === "function") {
      try { drag.animation.cancel(); } catch (_error) { /* already complete */ }
    }
    if (drag.timer !== null && drag.timer !== undefined && window && typeof window.clearTimeout === "function") {
      window.clearTimeout(drag.timer);
    }
    releasePointer(drag);
    if (drag.ghost && drag.ghost.isConnected) drag.ghost.remove();
    if (drag.card && drag.card.classList) {
      drag.card.classList.remove("hand-drag-source", "hand-dragging");
    }
    clearHighlights();
    if (active === drag) active = null;
  }

  async function animateBack(drag) {
    if (!drag || !drag.ghost) return;
    await waitForAnimation(drag, [
      { transform: drag.ghost.style.transform || "translate3d(0, 0, 0) scale(1)" },
      { transform: "translate3d(0, 0, 0) rotate(0deg) scale(1)", opacity: 1, offset: .74 },
      { transform: "translate3d(0, 0, 0) rotate(0deg) scale(1)", opacity: 0 },
    ], returnDuration, "cubic-bezier(.2,.8,.3,1)");
  }

  async function animateToDestination(drag, destination) {
    if (!drag || !drag.ghost || !destination) return;
    const width = drag.originRect.width || drag.ghost.offsetWidth || 100;
    const height = drag.originRect.height || drag.ghost.offsetHeight || 140;
    const end = { x: destination.x - width / 2, y: destination.y - height / 2 };
    const startTransform = drag.ghost.style.transform || "translate3d(0, 0, 0) scale(1)";
    await waitForAnimation(drag, [
      { transform: startTransform, opacity: 1 },
      { transform: ghostTransform(drag, end, .68), opacity: .08 },
    ], animationDuration, "cubic-bezier(.22,.78,.25,1)");
  }

  function selectionCallbacks(drag, resolved) {
    if (typeof onSelectSource === "function") onSelectSource("PLAY_CARD", drag.sourceId);
    if (resolved.kind === "target" && typeof onSelectTarget === "function") {
      onSelectTarget(resolved.targetId);
    }
    if (resolved.kind === "position" && typeof onSelectPosition === "function") {
      onSelectPosition(resolved.position);
    }
  }

  async function commitDrop(drag, resolved) {
    if (!drag || drag.cancelled) return;
    drag.settling = true;
    releasePointer(drag);
    await animateToDestination(drag, resolved.destination);
    if (drag.cancelled) return;
    const action = resolved.action;
    const index = actionIndex(action);
    cleanupDrag(drag);
    if (action && !actionNeedsBranch(action) && index >= 0 && typeof onSubmitIndex === "function") {
      drag.card.classList.add("hand-drag-committed");
      try {
        await onSubmitIndex(index, { preanimatedPlay: true });
      } finally {
        drag.card.classList.remove("hand-drag-committed");
      }
      return;
    }
    selectionCallbacks(drag, resolved);
  }

  async function rejectDrop(drag) {
    if (!drag || drag.cancelled) return;
    drag.settling = true;
    releasePointer(drag);
    await animateBack(drag);
    cleanupDrag(drag);
  }

  function beginDrag(drag, event) {
    if (!drag || drag.dragging) return;
    drag.dragging = true;
    drag.ghost = createGhost(drag);
    drag.card.classList.add("hand-drag-source", "hand-dragging");
    prepareDropFeedback(drag);
    moveGhost(drag, event);
    if (event.cancelable) event.preventDefault();
  }

  function onPointerDown(event) {
    if (active || !hand || (typeof getBusy === "function" && getBusy())) return;
    if (event.isPrimary === false || (event.button !== undefined && event.button !== 0)) return;
    const card = sourceCardForEvent(event);
    if (!card) return;
    const sourceId = nodeEntityId(card);
    const candidates = playActionsFor(sourceId);
    if (sourceId === null || !candidates.length) return;
    const rect = card.getBoundingClientRect();
    const drag = {
      card,
      sourceId,
      candidates,
      pointerId: event.pointerId,
      startPoint: pointFromEvent(event),
      originRect: rect,
      offset: { x: 0, y: 0 },
      dragging: false,
      settling: false,
      cancelled: false,
      ghost: null,
      animation: null,
      timer: null,
      positions: [],
      hover: null,
    };
    active = drag;
    if (typeof card.setPointerCapture === "function" && event.pointerId !== undefined) {
      try { card.setPointerCapture(event.pointerId); } catch (_error) { /* unsupported pointer capture */ }
    }
  }

  function onPointerMove(event) {
    const drag = active;
    if (!drag || drag.pointerId !== event.pointerId || drag.settling) return;
    const point = pointFromEvent(event);
    if (!drag.dragging && distanceSquared(point, drag.startPoint) < distanceThreshold * distanceThreshold) return;
    if (!drag.dragging) beginDrag(drag, event);
    if (!drag.ghost) return;
    moveGhost(drag, event);
    updateHover(drag, event);
    if (event.cancelable) event.preventDefault();
  }

  function onPointerUp(event) {
    const drag = active;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.dragging) {
      active = null;
      releasePointer(drag);
      return;
    }
    suppressClickCard = drag.card;
    if (suppressClickTimer !== null && window && typeof window.clearTimeout === "function") {
      window.clearTimeout(suppressClickTimer);
    }
    const setTimer = window && typeof window.setTimeout === "function" ? window.setTimeout.bind(window) : setTimeout;
    suppressClickTimer = setTimer(() => {
      suppressClickCard = null;
      suppressClickTimer = null;
    }, 700);
    if (event.cancelable) event.preventDefault();
    const resolved = resolveDrop(drag, event);
    if (resolved) {
      void commitDrop(drag, resolved);
    } else {
      void rejectDrop(drag);
    }
  }

  function onPointerCancel(event) {
    const drag = active;
    if (!drag || drag.pointerId !== event.pointerId) return;
    drag.cancelled = true;
    cleanupDrag(drag);
  }

  function onLostPointerCapture(event) {
    const drag = active;
    if (!drag || drag.pointerId !== event.pointerId || drag.settling) return;
    if (drag.dragging) {
      drag.cancelled = true;
      cleanupDrag(drag);
    } else {
      active = null;
    }
  }

  function onClick(event) {
    if (!suppressClickCard) return;
    const card = asElement(event.target);
    if (!card || !suppressClickCard.contains(card)) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClickCard = null;
    if (suppressClickTimer !== null && window && typeof window.clearTimeout === "function") {
      window.clearTimeout(suppressClickTimer);
    }
    suppressClickTimer = null;
  }

  function onNativeDragStart(event) {
    const target = asElement(event.target);
    if (target?.closest?.(".hand-card.playable")) event.preventDefault();
  }

  function bind() {
    if (bound || !hand || typeof hand.addEventListener !== "function") return;
    bound = true;
    hand.addEventListener("pointerdown", onPointerDown);
    hand.addEventListener("pointermove", onPointerMove);
    hand.addEventListener("pointerup", onPointerUp);
    hand.addEventListener("pointercancel", onPointerCancel);
    hand.addEventListener("lostpointercapture", onLostPointerCapture);
    hand.addEventListener("dragstart", onNativeDragStart, true);
    hand.addEventListener("click", onClick, true);
    if (window && typeof window.addEventListener === "function") {
      window.addEventListener("resize", () => {
        if (active && active.dragging) refreshPositionMarkers(active);
      });
    }
  }

  function cancel() {
    if (!active) {
      clearHighlights();
      suppressClickCard = null;
      if (suppressClickTimer !== null && window && typeof window.clearTimeout === "function") {
        window.clearTimeout(suppressClickTimer);
      }
      suppressClickTimer = null;
      return;
    }
    active.cancelled = true;
    cleanupDrag(active);
    suppressClickCard = null;
    if (suppressClickTimer !== null && window && typeof window.clearTimeout === "function") {
      window.clearTimeout(suppressClickTimer);
    }
    suppressClickTimer = null;
  }

  return { bind, cancel, isDragging: () => Boolean(active && active.dragging) };
}
