/**
 * Timeline driven battle effects.
 *
 * This module only presents effect telemetry supplied by the server.  It does
 * not infer game rules and deliberately keeps the old snapshot reconciliation
 * path in gui_presentation.js available for responses without telemetry.
 */
export function createEffects({
  document,
  window,
  elements,
  data,
  eventText,
  entityNode,
  center,
  animate,
  ghost,
  remove,
  reducedMotion,
}) {
  const artifacts = new Set();
  const timers = new Set();
  let generation = 0;

  function remember(node) {
    if (node) artifacts.add(node);
    return node;
  }

  function forget(node) {
    if (node) artifacts.delete(node);
    remove(node);
  }

  function text(value, fallback = "") {
    return data.safeText(value, fallback).trim();
  }

  function entityId(value) {
    return data.entityId(value);
  }

  function eventOf(entry) {
    if (!entry || typeof entry !== "object") return null;
    const event = entry.event && typeof entry.event === "object" ? entry.event : entry;
    return event && typeof event === "object" ? event : null;
  }

  function effectType(event) {
    return text(event && event.type, "").toUpperCase();
  }

  function sideForEvent(event) {
    const actor = text(event && event.actor, "self").toLowerCase();
    return actor === "opponent" || actor === "enemy" ? "opponent" : "self";
  }

  function deckCounter(event) {
    return elements[sideForEvent(event) === "opponent" ? "opponent-deck-count" : "deck-count"] || null;
  }

  function setEffectAttributes(node, event, typeOverride) {
    if (!node || !event) return node;
    const type = typeOverride || effectType(event);
    if (type) node.setAttribute("data-effect-type", type);
    const sourceId = entityId(event.source_entity_id);
    const targetId = entityId(event.target_entity_id);
    if (sourceId !== null) node.setAttribute("data-source-entity-id", String(sourceId));
    if (targetId !== null) node.setAttribute("data-target-entity-id", String(targetId));
    const batchId = text(event.batch_id, "");
    if (batchId) node.setAttribute("data-effect-batch-id", batchId);
    if (event.amount !== undefined && event.amount !== null) {
      node.setAttribute("data-effect-amount", String(event.amount));
    }
    if (event.actor !== undefined && event.actor !== null) {
      node.setAttribute("data-effect-actor", text(event.actor));
    }
    return node;
  }

  function entriesFrom(value) {
    return data.asArray(value).map(function (entry) {
      const event = eventOf(entry);
      return event ? { entry, event } : null;
    }).filter(Boolean);
  }

  function delay(ms) {
    return new Promise((resolve) => {
      const timer = { id: null, resolve };
      timer.id = window.setTimeout(() => {
        timers.delete(timer);
        resolve();
      }, Math.max(0, ms));
      timers.add(timer);
    });
  }

  function readableHold(ms = 420) {
    return reducedMotion && reducedMotion.matches ? delay(Math.min(ms, 520)) : Promise.resolve();
  }

  function targetPoint(event, context) {
    const targetId = entityId(event && event.target_entity_id);
    const sourceId = entityId(event && event.source_entity_id);
    const target = targetId === null ? null : entityNode(targetId);
    const source = sourceId === null ? null : entityNode(sourceId);
    const anchor = context && context.anchors && targetId !== null ? context.anchors.get(targetId) : null;
    return center(target || anchor || source) || center(elements.table) || { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  }

  function sourceNode(event, context) {
    const id = entityId(event && event.source_entity_id);
    if (id === null) return null;
    return entityNode(id) || (context && context.anchors && context.anchors.get(id)) || null;
  }

  function targetNode(event, context) {
    const id = entityId(event && event.target_entity_id);
    if (id === null) return null;
    return entityNode(id) || (context && context.anchors && context.anchors.get(id)) || null;
  }

  function appendArtifact(node) {
    if (!node) return null;
    remember(node);
    document.body.appendChild(node);
    return node;
  }

  function keepCaptionInViewport(label) {
    if (!label) return;
    const rect = label.getBoundingClientRect();
    const width = rect.width || label.offsetWidth || 0;
    const height = rect.height || label.offsetHeight || 0;
    const margin = 14;
    const viewportWidth = Math.max(1, data.safeNumber(window.innerWidth, 1));
    const viewportHeight = Math.max(1, data.safeNumber(window.innerHeight, 1));
    const halfWidth = width / 2;
    const minX = width ? halfWidth + margin : margin;
    const maxX = width ? Math.max(minX, viewportWidth - halfWidth - margin) : viewportWidth - margin;
    const currentX = data.safeNumber(parseFloat(label.style.left), viewportWidth / 2);
    const currentY = data.safeNumber(parseFloat(label.style.top), viewportHeight / 2);
    const minY = margin;
    const maxY = height ? Math.max(minY, viewportHeight - height - margin - 4) : viewportHeight - margin;
    const y = Math.max(minY, Math.min(maxY, currentY));
    label.style.left = `${Math.max(minX, Math.min(maxX, currentX))}px`;
    label.style.top = `${y}px`;
  }

  function caption(event, className, point, typeOverride, options = {}) {
    const label = document.createElement("span");
    label.className = `presentation-effect-caption ${className || ""}`.trim();
    setEffectAttributes(label, event, typeOverride);
    label.textContent = eventText(event);
    label.setAttribute("aria-live", "polite");
    label.style.left = `${point.x}px`;
    label.style.top = `${point.y}px`;
    const result = appendArtifact(label);
    if (options.keepInViewport) keepCaptionInViewport(result);
    return result;
  }

  function numberLabel(event, kind, point, value) {
    const label = document.createElement("span");
    label.className = `presentation-number presentation-${kind}`;
    setEffectAttributes(label, event, effectType(event));
    label.textContent = value;
    label.setAttribute("aria-label", eventText(event));
    label.style.left = `${point.x}px`;
    label.style.top = `${point.y}px`;
    return appendArtifact(label);
  }

  function pulse(node, kind = "trigger") {
    if (!node || !node.isConnected) return Promise.resolve();
    const type = kind.toLowerCase();
    const keyframes = type === "damage" ? [
      { filter: "brightness(1)", transform: "scale(1)" },
      { filter: "brightness(1.9) sepia(.65) saturate(1.35)", transform: "scale(1.1)", offset: .35 },
      { filter: "brightness(1)", transform: "scale(1)" },
    ] : type === "death" || type === "destroy" ? [
      { filter: "brightness(1)", transform: "scale(1)" },
      { filter: "brightness(1.8) grayscale(.3)", transform: "scale(1.08)", offset: .35 },
      { filter: "brightness(.72) grayscale(.85)", transform: "scale(.96)" },
    ] : [
      { filter: "brightness(1)", transform: "scale(1)" },
      { filter: "brightness(1.75) saturate(1.3)", transform: "scale(1.07)", offset: .45 },
      { filter: "brightness(1)", transform: "scale(1)" },
    ];
    return animate(node, keyframes, type === "damage" ? 430 : 390);
  }

  function pulseDeck(node) {
    if (!node || !node.isConnected) return Promise.resolve();
    return animate(node, [
      { filter: "brightness(1)", transform: "translateX(0) scale(1)" },
      { filter: "brightness(1.8) saturate(1.35)", transform: "translateX(-4px) scale(1.08)", offset: .2 },
      { filter: "brightness(1.8) saturate(1.35)", transform: "translateX(4px) scale(1.08)", offset: .4 },
      { filter: "brightness(1.3) saturate(1.15)", transform: "translateX(-3px) scale(1.04)", offset: .6 },
      { filter: "brightness(1)", transform: "translateX(0) scale(1)" },
    ], 460, "ease-in-out");
  }

  function float(label, finalTransform = "translate(-50%, -44px) scale(1)") {
    if (!label) return Promise.resolve();
    if (reducedMotion && reducedMotion.matches) {
      label.style.opacity = "1";
      return readableHold(520).finally(() => forget(label));
    }
    return animate(label, [
      { opacity: 0, transform: "translate(-50%, 0) scale(.72)" },
      { opacity: 1, transform: "translate(-50%, -12px) scale(1.08)", offset: .3 },
      { opacity: 0, transform: finalTransform },
    ], 640).then(() => readableHold(420)).finally(() => forget(label));
  }

  function showCaption(label, ms = 600) {
    if (!label) return Promise.resolve();
    if (reducedMotion && reducedMotion.matches) {
      label.style.opacity = "1";
      return readableHold(520).finally(() => forget(label));
    }
    const normal = animate(label, [
      { opacity: 0, transform: "translate(-50%, 4px) scale(.92)" },
      { opacity: 1, transform: "translate(-50%, 0) scale(1)", offset: .2 },
      { opacity: 0, transform: "translate(-50%, -12px) scale(1.02)" },
    ], ms);
    return normal.then(() => readableHold(420)).finally(() => forget(label));
  }

  function sourceAnchorVisible(anchor, event) {
    if (!anchor) return;
    if (typeof anchor.getAnimations === "function") {
      anchor.getAnimations().forEach((animation) => animation.cancel());
    }
    anchor.style.opacity = "1";
    anchor.style.filter = "none";
    anchor.style.transform = "none";
    anchor.style.visibility = "visible";
    setEffectAttributes(anchor, event, effectType(event));
    anchor.classList.add("presentation-source-anchor");
  }

  function hideAnchor(node) {
    if (node && node.classList.contains("presentation-effect-anchor")) {
      node.style.visibility = "hidden";
    }
  }

  function captureAnchors(entries) {
    const ids = new Set();
    entriesFrom(entries).forEach(({ event }) => {
      [event.source_entity_id, event.target_entity_id].forEach((value) => {
        const id = entityId(value);
        if (id !== null) ids.add(id);
      });
    });
    const anchors = new Map();
    ids.forEach((id) => {
      const node = entityNode(id);
      if (!node) return;
      const clone = ghost(node);
      if (!clone) return;
      clone.style.visibility = "hidden";
      clone.classList.add("presentation-effect-anchor");
      anchors.set(id, remember(clone));
    });
    return anchors;
  }

  function releaseAnchors(anchors) {
    if (!anchors) return;
    anchors.forEach((anchor) => {
      artifacts.delete(anchor);
      remove(anchor);
    });
    anchors.clear();
  }

  async function playTrigger(entry, context, kind) {
    const event = eventOf(entry);
    if (!event) return;
    const node = sourceNode(event, context);
    const anchor = node && node.classList.contains("presentation-effect-anchor") ? node : null;
    sourceAnchorVisible(anchor, event);
    const point = center(node) || targetPoint(event, context);
    const label = caption(event, `presentation-${kind.toLowerCase()}`, { x: point.x, y: point.y - 18 }, kind);
    const pulsePromise = node ? pulse(node, "trigger") : Promise.resolve();
    const labelPromise = showCaption(label, kind === "DEATHRATTLE" ? 650 : 560);
    await Promise.all([pulsePromise, labelPromise]);
    hideAnchor(anchor);
  }

  async function playDamageGroup(entries, context) {
    const jobs = [];
    const firstEvent = eventOf(entries[0]);
    const firstPoint = targetPoint(firstEvent, context);
    const sourceAnchors = new Set();
    entries.forEach(({ event }) => {
      const target = targetNode(event, context);
      const source = sourceNode(event, context);
      if (source && source.classList.contains("presentation-effect-anchor")) {
        sourceAnchorVisible(source, event);
        sourceAnchors.add(source);
      }
      const point = center(target) || targetPoint(event, context);
      const amount = data.safeNumber(event.amount, 0);
      const shieldBreak = amount <= 0 && event.shield_broken === true;
      const label = numberLabel(event, shieldBreak ? "shield-break" : "damage", {
        x: point.x,
        y: point.y,
      }, shieldBreak ? "✦" : (amount <= 0 ? "0" : `−${amount}`));
      const targetPulse = target ? pulse(target, "damage") : Promise.resolve();
      const bolt = event.combat_damage === true
        ? null
        : source && target && source !== target ? makeBolt(source, target, event) : null;
      jobs.push(Promise.all([
        targetPulse,
        float(label),
        bolt ? playBolt(bolt, source, target) : Promise.resolve(),
      ]));
    });
    const copy = caption(firstEvent, "presentation-damage-copy", {
      x: firstPoint.x,
      y: firstPoint.y + 22,
    }, "DAMAGE");
    await Promise.all([...jobs, showCaption(copy, entries.length > 1 ? 620 : 500)]);
    sourceAnchors.forEach(hideAnchor);
  }

  function makeBolt(source, target, event) {
    const from = center(source);
    const to = center(target);
    if (!from || !to) return null;
    const bolt = document.createElement("span");
    bolt.className = "presentation-bolt presentation-effect-bolt";
    setEffectAttributes(bolt, event, "DAMAGE");
    bolt.style.left = `${from.x}px`;
    bolt.style.top = `${from.y}px`;
    bolt.style.setProperty("--bolt-x", `${to.x - from.x}px`);
    bolt.style.setProperty("--bolt-y", `${to.y - from.y}px`);
    return appendArtifact(bolt);
  }

  function playBolt(bolt) {
    return animate(bolt, [
      { transform: "translate(-50%, -50%) scale(.55)", opacity: .25 },
      { transform: "translate(calc(-50% + var(--bolt-x)), calc(-50% + var(--bolt-y))) scale(1.2)", opacity: 1 },
    ], 360, "ease-out").finally(() => forget(bolt));
  }

  async function playValue(entry, context, kind) {
    const event = eventOf(entry);
    if (!event) return;
    const target = targetNode(event, context);
    const point = center(target) || targetPoint(event, context);
    const amount = data.safeNumber(event.amount, 0);
    const label = numberLabel(event, kind.toLowerCase(), point, `+${amount}`);
    const copy = caption(event, `presentation-${kind.toLowerCase()}-copy`, {
      x: point.x,
      y: point.y + 22,
    }, kind);
    await Promise.all([
      target ? pulse(target, kind.toLowerCase()) : Promise.resolve(),
      float(label),
      showCaption(copy, 520),
    ]);
  }

  async function playDeckCue(entry) {
    const event = eventOf(entry);
    if (!event) return;
    const target = deckCounter(event);
    const point = center(target) || center(elements.table) || {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    };
    const type = effectType(event);
    const label = caption(event, `presentation-${type.toLowerCase().replace(/_/g, "-")}-copy`, {
      x: point.x,
      y: point.y - 18,
    }, type, { keepInViewport: true });
    await Promise.all([
      target ? pulseDeck(target) : Promise.resolve(),
      showCaption(label, type === "FATIGUE" ? 620 : 520),
    ]);
  }

  async function playDeathGroup(entries, context, kind) {
    const jobs = [];
    const firstEvent = eventOf(entries[0]);
    const firstPoint = targetPoint(firstEvent, context);
    entries.forEach(({ event }) => {
      const target = targetNode(event, context);
      setEffectAttributes(target, event, kind);
      if (target && target.classList.contains("presentation-effect-anchor")) sourceAnchorVisible(target, event);
      const point = center(target) || targetPoint(event, context);
      const fade = target ? (reducedMotion && reducedMotion.matches
        ? readableHold(520).then(() => {
          target.style.opacity = "0";
          hideAnchor(target);
        })
        : animate(target, [
          { opacity: 1, filter: "brightness(1)", transform: "scale(1)" },
          { opacity: .82, filter: "brightness(1.9) grayscale(.5)", transform: "scale(1.1)", offset: .32 },
          { opacity: 0, filter: "brightness(.35) grayscale(1)", transform: "scale(.45) rotate(10deg)" },
        ], kind === "DESTROY" ? 500 : 580).then(() => hideAnchor(target))) : Promise.resolve();
      jobs.push(fade);
    });
    const copy = caption(firstEvent, `presentation-${kind.toLowerCase()}-copy`, firstPoint, kind);
    await Promise.all([...jobs, showCaption(copy, entries.length > 1 ? 620 : (kind === "DESTROY" ? 500 : 620))]);
  }

  async function playDestroy(entry, context) {
    const event = eventOf(entry);
    if (!event) return;
    const target = targetNode(event, context);
    setEffectAttributes(target, event, "DESTROY");
    if (target && target.classList.contains("presentation-effect-anchor")) sourceAnchorVisible(target, event);
    const point = center(target) || targetPoint(event, context);
    const copy = caption(event, "presentation-destroy-copy", point, "DESTROY");
    const cue = target ? (reducedMotion && reducedMotion.matches
      ? readableHold(420)
      : animate(target, [
        { filter: "brightness(1)", transform: "scale(1)" },
        { filter: "brightness(1.9) sepia(.35)", transform: "scale(1.08) rotate(-2deg)", offset: .4 },
        { filter: "brightness(1)", transform: "scale(1) rotate(0)" },
      ], 430)) : Promise.resolve();
    await Promise.all([cue, showCaption(copy, 500)]);
    hideAnchor(target);
  }

  async function playSummon(entry, context) {
    const event = eventOf(entry);
    if (!event) return;
    const target = targetNode(event, context) || sourceNode(event, context);
    const point = center(target) || targetPoint(event, context);
    const copy = caption(event, "presentation-summon-copy", {
      x: point.x,
      y: point.y - 20,
    }, "SUMMON");
    const intro = target ? animate(target, [
      { opacity: 0, transform: "translateY(-28px) scale(.58)", filter: "brightness(1.8)" },
      { opacity: 1, transform: "translateY(0) scale(1)", filter: "brightness(1)" },
    ], 470, "cubic-bezier(.18,.85,.27,1)") : Promise.resolve();
    await Promise.all([intro, showCaption(copy, 560)]);
  }

  async function playSingle(entry, context) {
    const event = eventOf(entry);
    const type = effectType(event);
    if (!event) return;
    if (type === "BATTLECRY" || type === "DEATHRATTLE") return playTrigger(entry, context, type);
    if (type === "HEAL" || type === "ARMOR") return playValue(entry, context, type);
    if (type === "DECK_EMPTY" || type === "DECK_DESTROY" || type === "FATIGUE") {
      return playDeckCue(entry, context);
    }
    if (type === "SUMMON") return playSummon(entry, context);
    if (type === "DEATH") return playDeathGroup([entry], context, type);
    if (type === "DESTROY") return playDestroy(entry, context);
    if (type === "DAMAGE") return playDamageGroup([entry], context);
    // A future event kind should still be readable when the server sends it.
    const point = targetPoint(event, context);
    await showCaption(caption(event, "presentation-effect-copy", point, type), 520);
  }

  function sameBatch(left, right, type) {
    const leftEvent = eventOf(left);
    const rightEvent = eventOf(right);
    if (!leftEvent || !rightEvent || effectType(leftEvent) !== type || effectType(rightEvent) !== type) return false;
    const leftBatch = text(leftEvent.batch_id, "");
    const rightBatch = text(rightEvent.batch_id, "");
    return Boolean(leftBatch) && leftBatch === rightBatch;
  }

  async function play(entries, context = {}) {
    const playGeneration = generation;
    const isLive = () => playGeneration === generation && (!context.isCurrent || context.isCurrent());
    const normalized = entriesFrom(entries);
    let index = 0;
    while (index < normalized.length) {
      if (!isLive()) return false;
      const current = normalized[index];
      const type = effectType(current.event);
      if (type === "DAMAGE" && text(current.event.batch_id, "")) {
        const batch = [current];
        while (index + batch.length < normalized.length && sameBatch(current, normalized[index + batch.length], "DAMAGE")) {
          batch.push(normalized[index + batch.length]);
        }
        await playDamageGroup(batch, context);
        if (!isLive()) return false;
        index += batch.length;
        continue;
      }
      if (type === "DEATH") {
        const deaths = [current];
        while (index + deaths.length < normalized.length && sameBatch(current, normalized[index + deaths.length], "DEATH")) {
          deaths.push(normalized[index + deaths.length]);
        }
        await playDeathGroup(deaths, context, "DEATH");
        if (!isLive()) return false;
        index += deaths.length;
        continue;
      }
      await playSingle(current, context);
      if (!isLive()) return false;
      index += 1;
    }
    return true;
  }

  function playDeckCueEvent(event, context = {}) {
    return play([{ event }], context);
  }

  function cancel() {
    generation += 1;
    timers.forEach((timer) => {
      window.clearTimeout(timer.id);
      timer.resolve();
    });
    timers.clear();
    artifacts.forEach(remove);
    artifacts.clear();
  }

  return { captureAnchors, cancel, play, playDeckCue: playDeckCueEvent, releaseAnchors };
}
