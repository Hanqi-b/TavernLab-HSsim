/** Visual playback for public, already resolved Actions. Never decides game rules. */
export function createPresentation({ document, window, elements, data, eventText }) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let active = new Set();

  const duration = (normal) => reducedMotion.matches ? 1 : normal;
  const idOf = (card) => data.entityId(card && card.entity_id);
  const asCards = (value) => data.asArray(value);

  function entityNode(id) {
    if (id === null || id === undefined) return null;
    return [elements["self-board"], elements["opponent-board"], elements["self-hero-row"],
      elements["opponent-hero-row"], elements.hand, elements["hero-power-row"]]
      .map((root) => root && root.querySelector(`[data-entity-id="${String(id)}"]`))
      .find(Boolean) || null;
  }

  function center(node) {
    if (!node) return null;
    const box = node.getBoundingClientRect();
    return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
  }

  function publicCharacters(observation) {
    const found = new Map();
    for (const side of [observation?.self, observation?.opponent]) {
      for (const card of [side?.hero, ...asCards(side?.board)]) {
        const id = idOf(card);
        if (id !== null) found.set(id, card);
      }
    }
    return found;
  }

  function track(animation, ms) {
    active.add(animation);
    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        active.delete(animation);
        resolve();
      };
      // Browsers can throttle WAAPI on an inactive tab. Keep the action queue
      // bounded so a match can resume when the tab becomes visible again.
      const timer = window.setTimeout(() => {
        try { animation.cancel(); } finally { finish(); }
      }, ms + 350);
      animation.finished.then(finish, finish);
    });
  }

  function animate(node, keyframes, ms, easing = "ease-in-out") {
    if (!node || !node.isConnected) return Promise.resolve();
    const playDuration = duration(ms);
    return track(node.animate(keyframes, { duration: playDuration, easing, fill: "both" }), playDuration);
  }

  function ghost(node) {
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    const clone = node.cloneNode(true);
    clone.classList.add("presentation-ghost");
    clone.setAttribute("aria-hidden", "true");
    clone.inert = true;
    clone.removeAttribute("role");
    clone.removeAttribute("tabindex");
    clone.removeAttribute("id");
    clone.querySelectorAll("[id]").forEach((child) => child.removeAttribute("id"));
    clone.querySelectorAll("[tabindex]").forEach((child) => child.removeAttribute("tabindex"));
    Object.assign(clone.style, {
      position: "fixed", left: `${rect.left}px`, top: `${rect.top}px`,
      width: `${rect.width}px`, height: `${rect.height}px`, margin: "0",
      transform: "none", pointerEvents: "none", zIndex: "1000",
    });
    document.body.appendChild(clone);
    return clone;
  }

  function remove(node) { if (node && node.isConnected) node.remove(); }

  function boardDestination(frame, event) {
    const side = event.actor === "opponent" ? "opponent-board" : "self-board";
    const board = elements[side];
    if (!board) return null;
    const cards = asCards(frame.observation?.[event.actor === "opponent" ? "opponent" : "self"]?.board);
    const index = cards.findIndex((card) => idOf(card) === event.source_entity_id);
    if (index >= 0) {
      const rect = board.getBoundingClientRect();
      const current = board.querySelector(".board-card");
      const currentRect = current?.getBoundingClientRect();
      const minWidth = current ? parseFloat(window.getComputedStyle(current).minWidth) || 52 : 52;
      const oldWidth = board.querySelector(".board-slot") ? 96 : currentRect?.width || 96;
      const width = Math.max(minWidth, Math.min(oldWidth, rect.width / cards.length));
      const left = rect.left + (rect.width - width * cards.length) / 2;
      return { x: left + width * (index + .5), y: currentRect ? center(current).y : rect.top + rect.height / 2 };
    }
    return center(entityNode(event.target_entity_id)) || center(board);
  }

  function openingNode(event) {
    if (event.type === "PLAY_CARD") {
      return event.actor === "self" ? entityNode(event.source_entity_id) :
        elements["opponent-hand"]?.querySelector(".hidden-card:last-child");
    }
    if (event.type === "USE_HERO_POWER") {
      return entityNode(event.source_entity_id) ||
        elements[event.actor === "self" ? "self-hero-row" : "opponent-hero-row"]?.firstElementChild;
    }
    return entityNode(event.source_entity_id);
  }

  async function playIntent(event, frame) {
    if (!event) return;
    const source = openingNode(event);
    const target = entityNode(event.target_entity_id);
    if (event.type === "ATTACK" && source && target) {
      const from = center(source);
      const to = center(target);
      const dx = (to.x - from.x) * .72;
      const dy = (to.y - from.y) * .72;
      await animate(source, [
        { transform: "translate(0, 0) scale(1)" },
        { transform: `translate(${dx}px, ${dy}px) scale(1.08)`, offset: .58 },
        { transform: "translate(0, 0) scale(1)" },
      ], 570, "cubic-bezier(.2,.8,.2,1)");
      return;
    }
    if (event.type === "PLAY_CARD" && source) {
      const from = center(source);
      const to = boardDestination(frame, event);
      if (!from || !to) return;
      const clone = ghost(source);
      if (!clone) return;
      const originalOpacity = source.style.opacity;
      source.style.opacity = "0";
      try {
        await animate(clone, [
          { transform: "translate(0, 0) scale(1)", opacity: 1 },
          { transform: `translate(${to.x - from.x}px, ${to.y - from.y}px) scale(.76)`, opacity: .96, offset: .78 },
          { transform: `translate(${to.x - from.x}px, ${to.y - from.y}px) scale(.58)`, opacity: 0 },
        ], 490, "cubic-bezier(.22,.78,.25,1)");
      } finally {
        source.style.opacity = originalOpacity;
        remove(clone);
      }
      return;
    }
    if (event.type === "USE_HERO_POWER" && source) {
      const from = center(source);
      const to = center(target);
      if (to) {
        const bolt = document.createElement("div");
        bolt.className = "presentation-bolt";
        bolt.style.left = `${from.x}px`;
        bolt.style.top = `${from.y}px`;
        document.body.appendChild(bolt);
        try {
          await animate(bolt, [
            { transform: "translate(-50%, -50%) scale(.7)", opacity: .5 },
            { transform: `translate(calc(-50% + ${to.x - from.x}px), calc(-50% + ${to.y - from.y}px)) scale(1.25)`, opacity: 1 },
          ], 400, "ease-out");
        } finally { remove(bolt); }
      } else {
        await animate(source, [
          { filter: "brightness(1)", transform: "scale(1)" },
          { filter: "brightness(1.7)", transform: "scale(1.13)", offset: .5 },
          { filter: "brightness(1)", transform: "scale(1)" },
        ], 410);
      }
      return;
    }
    if (event.type === "END_TURN") {
      await turnBanner(event);
    }
  }

  async function turnBanner(event) {
    const banner = document.createElement("div");
    banner.className = "presentation-turn";
    banner.textContent = eventText(event);
    const table = elements.table || elements.game?.querySelector(".table");
    if (!table) return;
    table.appendChild(banner);
    try {
      await animate(banner, [
        { opacity: 0, transform: "translate(-50%, -50%) scale(.82)" },
        { opacity: 1, transform: "translate(-50%, -50%) scale(1)", offset: .35 },
        { opacity: 0, transform: "translate(-50%, -55%) scale(1.04)" },
      ], 680);
    } finally { remove(banner); }
  }

  function boardPositions() {
    const positions = new Map();
    for (const root of [elements["self-board"], elements["opponent-board"]]) {
      root?.querySelectorAll(".board-card[data-entity-id]").forEach((node) => {
        const id = data.entityId(node.dataset.entityId);
        if (id !== null) positions.set(id, node.getBoundingClientRect());
      });
    }
    return positions;
  }

  function animateBoardReflow(before) {
    const motions = [];
    for (const [id, oldRect] of before) {
      const node = entityNode(id);
      if (!node || !node.classList.contains("board-card")) continue;
      const rect = node.getBoundingClientRect();
      const dx = oldRect.left - rect.left;
      const dy = oldRect.top - rect.top;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        motions.push(animate(node, [
          { transform: `translate(${dx}px, ${dy}px)` },
          { transform: "translate(0, 0)" },
        ], 330, "cubic-bezier(.2,.8,.25,1)"));
      }
    }
    return Promise.all(motions);
  }

  function impact(node, amount, kind) {
    if (!node) return Promise.resolve();
    const pulse = animate(node, kind === "damage" ? [
      { filter: "brightness(1)", transform: "scale(1)" },
      { filter: "brightness(1.8) sepia(.5)", transform: "scale(1.1)", offset: .35 },
      { filter: "brightness(1)", transform: "scale(1)" },
    ] : [
      { filter: "brightness(1)", transform: "scale(1)" },
      { filter: "brightness(1.6)", transform: "scale(1.06)", offset: .45 },
      { filter: "brightness(1)", transform: "scale(1)" },
    ], 450);
    if (amount <= 0) return pulse;
    const label = document.createElement("span");
    label.className = `presentation-number presentation-${kind}`;
    label.textContent = `${kind === "damage" ? "−" : "+"}${amount}`;
    const point = center(node);
    label.style.left = `${point.x}px`;
    label.style.top = `${point.y}px`;
    document.body.appendChild(label);
    const float = animate(label, [
      { opacity: 0, transform: "translate(-50%, 0) scale(.7)" },
      { opacity: 1, transform: "translate(-50%, -14px) scale(1.15)", offset: .35 },
      { opacity: 0, transform: "translate(-50%, -42px) scale(1)" },
    ], 700).finally(() => remove(label));
    return Promise.all([pulse, float]);
  }

  function collectDeaths(previous, next) {
    const now = publicCharacters(next);
    const ghosts = [];
    for (const [id, card] of publicCharacters(previous)) {
      if (now.has(id)) continue;
      const node = entityNode(id);
      if (node && node.classList.contains("board-card")) ghosts.push(ghost(node));
    }
    return ghosts.filter(Boolean);
  }

  function damageChanges(previous, next) {
    const before = publicCharacters(previous);
    const after = publicCharacters(next);
    const changes = [];
    for (const [id, card] of after) {
      const old = before.get(id);
      if (!old) continue;
      const oldHealth = data.safeNumber(old.health, 0);
      const newHealth = data.safeNumber(card.health, 0);
      const oldArmor = data.safeNumber(old.armor, 0);
      const newArmor = data.safeNumber(card.armor, 0);
      const lost = Math.max(0, oldHealth - newHealth) + Math.max(0, oldArmor - newArmor);
      if (lost) changes.push({ id, amount: lost, kind: "damage" });
      else if (newHealth > oldHealth) changes.push({ id, amount: newHealth - oldHealth, kind: "heal" });
      else if (newArmor > oldArmor) changes.push({ id, amount: newArmor - oldArmor, kind: "armor" });
      else if (old.divine_shield && !card.divine_shield) changes.push({ id, amount: 0, kind: "damage" });
    }
    return changes;
  }

  function draws(previous, next) {
    const output = [];
    for (const side of ["self", "opponent"]) {
      const oldSide = previous?.[side] || {};
      const nextSide = next?.[side] || {};
      const deckDecrease = data.safeNumber(oldSide.deck_count, 0) -
        data.safeNumber(nextSide.deck_count, 0);
      if (deckDecrease <= 0) continue;
      if (side === "self") {
        const oldIds = new Set(asCards(oldSide.hand).map(idOf));
        for (const card of asCards(nextSide.hand)) {
          const id = idOf(card);
          if (id !== null && !oldIds.has(id)) output.push({ side, id });
        }
      } else {
        const handIncrease = data.safeNumber(nextSide.hand_count, 0) -
          data.safeNumber(oldSide.hand_count, 0);
        for (let index = 0; index < Math.min(deckDecrease, handIncrease); index += 1) {
          output.push({ side, index });
        }
      }
    }
    return output;
  }

  async function resolve(previous, next, deaths, reflow) {
    const changes = damageChanges(previous, next);
    const pulses = changes.map(({ id, amount, kind }) => impact(entityNode(id), amount, kind));
    const oldCharacters = publicCharacters(previous);
    for (const [id] of publicCharacters(next)) {
      if (oldCharacters.has(id)) continue;
      const node = entityNode(id);
      if (node && node.classList.contains("board-card")) pulses.push(animate(node, [
        { opacity: 0, transform: "translateY(-28px) scale(.55)", filter: "brightness(1.7)" },
        { opacity: 1, transform: "translateY(0) scale(1)", filter: "brightness(1)" },
      ], 470, "cubic-bezier(.18,.85,.27,1)"));
    }
    for (const draw of draws(previous, next)) {
      const root = elements[draw.side === "self" ? "hand" : "opponent-hand"];
      const card = draw.side === "self"
        ? root?.querySelector(`[data-entity-id="${draw.id}"]`)
        : root?.children[root.children.length - 1 - draw.index];
      if (card) pulses.push(animate(card, [
        { opacity: 0, transform: "translate(70px, -65px) scale(.55) rotate(12deg)" },
        { opacity: 1, transform: "translate(0, 0) scale(1) rotate(0)" },
      ], 480, "cubic-bezier(.2,.8,.2,1)"));
    }
    deaths.forEach((node) => pulses.push(animate(node, [
      { opacity: 1, filter: "brightness(1)", transform: "scale(1)" },
      { opacity: .8, filter: "brightness(2) grayscale(.5)", transform: "scale(1.12)", offset: .35 },
      { opacity: 0, filter: "brightness(.4) grayscale(1)", transform: "scale(.4) rotate(12deg)" },
    ], 580).finally(() => remove(node))));
    pulses.push(reflow);
    await Promise.all(pulses);
  }

  /** Reconcile one presentation frame, then the authoritative final snapshot. */
  async function play(steps, finalSnapshot, applySnapshot, isCurrent, options = {}) {
    const initial = finalSnapshot && finalSnapshot.session_id;
    for (const [index, frame] of steps.entries()) {
      if (!isCurrent() || !frame || !frame.observation || initial !== finalSnapshot.session_id) return;
      const prior = applySnapshot.current();
      if (!prior || prior.session_id !== initial || frame.revision <= prior.revision) continue;
      const event = frame.event;
      if (event) {
        const notice = elements.notice;
        if (notice) { notice.textContent = eventText(event); notice.hidden = false; }
      }
      if (!(index === 0 && options.skipFirstIntent && event?.actor === "self" && event.type === "PLAY_CARD")) {
        await playIntent(event, frame);
      }
      if (!isCurrent()) return;
      const priorObservation = prior.observation || {};
      const deaths = collectDeaths(priorObservation, frame.observation);
      const before = boardPositions();
      const events = [...(prior.events || []), ...(event ? [event] : [])];
      const transient = {
        session_id: initial, revision: frame.revision, observation: frame.observation,
        legal_actions: [], outcome: null, events,
      };
      applySnapshot.commit(transient);
      await resolve(priorObservation, frame.observation, deaths, animateBoardReflow(before));
    }
    if (isCurrent()) {
      if (typeof options.beforeFinal === "function") options.beforeFinal();
      applySnapshot.commit(finalSnapshot, true);
    }
  }

  function cancel() {
    for (const animation of active) animation.cancel();
    active.clear();
    document.querySelectorAll(".presentation-ghost, .presentation-bolt, .presentation-number, .presentation-turn")
      .forEach(remove);
  }

  return { play, cancel, boardPositions, animateBoardReflow };
}
