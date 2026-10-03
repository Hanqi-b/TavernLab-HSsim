#!/usr/bin/env node
/* Real-engine browser checks for lethal damage, AOE, and chained deathrattles. */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const python = process.env.FIREPLACE_GUI_PYTHON || path.join(root, "venv/bin/python");
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-effect-artifacts");

function fixture(scenario) {
  const child = spawn(python, ["-u", "tests/web_gui_effects_fixture.py", "--scenario", scenario], {
    cwd: root, stdio: ["ignore", "pipe", "pipe"],
  });
  let diagnostics = "";
  child.stderr.on("data", chunk => { diagnostics += chunk; });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture timed out: ${diagnostics}`)), 30000);
    readline.createInterface({ input: child.stdout }).on("line", line => {
      try {
        const value = JSON.parse(line);
        if (value.url) { clearTimeout(timer); resolve(value.url); }
      } catch (_) { /* Engine diagnostics precede the readiness message. */ }
    });
    child.once("error", error => { clearTimeout(timer); reject(error); });
    child.once("exit", code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${diagnostics}`)); });
  });
  return { child, ready };
}

async function state(page) {
  return page.evaluate(async () => (await fetch("/api/state")).json());
}

async function idle(page) {
  await page.waitForFunction(() => window.fireplaceWebGui && !window.fireplaceWebGui.isBusy(),
    null, { timeout: 90000 });
}

async function traceEffects(page) {
  await page.evaluate(() => {
    window.__effectTrace = [];
    window.__handEntrances = [];
    window.__projectileTrace = [];
    window.__boardMotionTrace = [];
    window.__boardPositionTrace = [];
    window.__latestEventStarts = [];
    const originalAnimate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      if (this.classList.contains("hand-card") && Array.isArray(keyframes) &&
          keyframes.some(frame => frame.opacity === 0 && String(frame.transform).includes("translate(70px"))) {
        window.__handEntrances.push({ id: Number(this.dataset.entityId), time: performance.now() });
      }
      if (this.classList.contains("presentation-bolt")) {
        window.__projectileTrace.push({
          time: performance.now(),
          type: this.dataset.effectType || "",
          target: Number(this.dataset.targetEntityId || 0),
        });
      }
      if (this.classList.contains("board-card") && Array.isArray(keyframes) && keyframes.length === 2) {
        const match = /^translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)$/.exec(String(keyframes[0].transform || ""));
        if (match && keyframes[1].transform === "translate(0, 0)") {
          const box = this.getBoundingClientRect();
          window.__boardMotionTrace.push({
            id: Number(this.dataset.entityId), time: performance.now(), left: box.left,
            startLeft: box.left + Number(match[1]), translateX: Number(match[1]),
          });
        }
      }
      return originalAnimate.call(this, keyframes, options);
    };
    document.addEventListener("animationstart", event => {
      if (event.animationName !== "event-in" || !event.target.matches(".event-item.latest")) return;
      window.__latestEventStarts.push({
        time: performance.now(), text: event.target.textContent.trim(),
        seq: event.target.dataset.eventSeq || "",
      });
    }, true);
    function scanBoardPositions() {
      const board = document.getElementById("opponent-board");
      const nodes = [...(board?.querySelectorAll(".board-card[data-entity-id]") || [])];
      const ids = nodes.map(node => Number(node.dataset.entityId));
      for (const node of nodes) {
        window.__boardPositionTrace.push({
          id: Number(node.dataset.entityId), left: node.getBoundingClientRect().left,
          time: performance.now(), ids,
        });
      }
    }
    window.__boardPositionObserver = new MutationObserver(scanBoardPositions);
    const opponentBoard = document.getElementById("opponent-board");
    if (opponentBoard) window.__boardPositionObserver.observe(opponentBoard, { childList: true, subtree: true });
    scanBoardPositions();
    const seen = new WeakSet();
    function scan() {
      for (const node of document.querySelectorAll("[data-effect-type]")) {
        if (seen.has(node)) continue;
        seen.add(node);
        const box = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        window.__effectTrace.push({
          type: node.dataset.effectType,
          className: node.className,
          target: Number(node.dataset.targetEntityId || 0),
          source: Number(node.dataset.sourceEntityId || 0),
          text: node.textContent,
          time: performance.now(),
          rendered: box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden",
          bounds: { left: box.left, top: box.top, right: box.right, bottom: box.bottom },
          inlineLeft: node.style.left,
          computedLeft: style.left,
          computedRight: style.right,
          offsetLeft: node.offsetLeft,
          offsetWidth: node.offsetWidth,
          transform: style.transform,
          translate: style.translate,
          marginLeft: style.marginLeft,
          position: style.position,
          parentRect: (() => {
            const parent = node.parentElement;
            const rect = parent?.getBoundingClientRect();
            return rect ? { left: rect.left, right: rect.right, width: rect.width } : null;
          })(),
          bodyTransform: getComputedStyle(document.body).transform,
          htmlTransform: getComputedStyle(document.documentElement).transform,
          viewport: { width: window.innerWidth, height: window.innerHeight },
          withinViewport: box.left >= 0 && box.top >= 0 &&
            box.right <= window.innerWidth && box.bottom <= window.innerHeight,
          overlappingDeckEmpty: node.dataset.effectType === "FATIGUE"
            ? document.querySelectorAll('[data-effect-type="DECK_EMPTY"]').length
            : 0,
          concurrentDamage: [...document.querySelectorAll('[data-effect-type="DAMAGE"]')]
            .map(item => Number(item.dataset.targetEntityId || 0)),
        });
      }
    }
    window.__effectObserver = new MutationObserver(scan);
    window.__effectObserver.observe(document.body, { childList: true, subtree: true, attributes: true,
      attributeFilter: ["data-effect-type", "data-target-entity-id", "data-source-entity-id"] });
    scan();
  });
}

async function stopTraceEffects(page) {
  return page.evaluate(() => {
    window.__effectObserver.disconnect();
    window.__boardPositionObserver?.disconnect();
    return {
      projectiles: window.__projectileTrace,
      boardMotions: window.__boardMotionTrace,
      boardPositions: window.__boardPositionTrace,
      latestEventStarts: window.__latestEventStarts,
    };
  });
}

function assertPublicEffects(payload) {
  for (const effect of payload.presentation_steps.flatMap(frame => frame.effects || [])) {
    assert(!("hand" in effect.observation.opponent), "Effect snapshots must hide the opponent hand");
    assert(!("secrets" in effect.observation.opponent), "Effect snapshots must hide private secrets");
    assert(!Object.keys(effect.event).some(key => key.startsWith("_")), "Internal source metadata must stay private");
  }
}

function assertLatestEventAnimatedOnce(starts, latest, previousLatest, payload) {
  const newEvent = (payload.events || []).at(-1);
  const matching = newEvent && newEvent.seq !== undefined
    ? starts.filter(item => item.seq === String(newEvent.seq))
    : starts.filter(item => item.text === latest && item.text !== previousLatest);
  assert.equal(matching.length, 1,
    "The latest public log row must enter once for event " + (newEvent?.seq ?? latest) +
    "; previous=" + previousLatest + "; latest=" + latest + "; starts=" + JSON.stringify(starts));
}

async function submitFromUi(page, click, captureName = null) {
  const response = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/action");
  await click();
  const result = await response;
  assert.equal(result.status(), 200);
  const payload = await result.json();
  if (captureName) {
    await page.locator('[data-effect-type="DEATHRATTLE"]').first().waitFor({ state: "visible", timeout: 30000 });
    await page.screenshot({ path: path.join(artifacts, `${captureName}-trigger.png`) });
  }
  await idle(page);
  return payload;
}

function before(trace, earlierType, laterType, target) {
  const earlier = trace.findIndex(item => item.type === earlierType && item.target === target);
  const later = trace.findIndex(item => item.type === laterType && item.target === target);
  assert(earlier >= 0 && later > earlier,
    `Entity ${target}: ${earlierType} must appear before ${laterType}: ${JSON.stringify(trace)}`);
}

async function checkLongChainAndCancellation(page) {
  const result = await page.evaluate(async () => {
    const { createPresentation } = await import("/gui_presentation.js");
    const { createDataUtils } = await import("/gui_utils.js");
    const data = createDataUtils({ model: window.FireplaceActionModel,
      translate: key => key, getLocale: () => "zhCN" });
    const victim = { entity_id: 424241, name: "Tail victim", health: 1 };
    const drawn = { entity_id: 424242, name: "Tail draw" };
    const observation = { self: { board: [victim], hand: [], deck_count: 2 }, opponent: { board: [] } };
    const finalObservation = { self: { board: [], hand: [drawn], deck_count: 1 }, opponent: { board: [] } };
    const initial = { session_id: "long-chain-check", revision: 0, observation, events: [] };
    const final = { ...initial, observation: finalObservation, revision: 1, legal_actions: [], outcome: null };
    const frame = { revision: 1, observation: finalObservation, effects: Array.from({ length: 100 }, () => ({
      event: { type: "BATTLECRY", actor: "self" }, observation,
    })) };
    const board = document.createElement("div");
    const hand = document.createElement("div");
    document.body.append(board, hand);
    const motions = [];
    const previousAnimate = Element.prototype.animate;
    Element.prototype.animate = function (frames, options) {
      motions.push({ id: Number(this.dataset.entityId), ghost: this.classList.contains("presentation-ghost"),
        hand: this.classList.contains("hand-card"), frames });
      return previousAnimate.call(this, frames, options);
    };
    const notice = document.createElement("span");
    const presentation = createPresentation({ document, window,
      elements: { notice, "self-board": board, hand }, data,
      eventText: event => event.type });
    let current = initial;
    let finalCommits = 0;
    let resumed = false;
    const adapter = { current: () => current, commit: (snapshot, isFinal) => {
      current = snapshot;
      if (isFinal) finalCommits += 1;
      for (const [root, cards, className] of [
        [board, snapshot.observation.self.board, "board-card"],
        [hand, snapshot.observation.self.hand, "hand-card"],
      ]) {
        root.replaceChildren(...cards.map(card => {
          const node = document.createElement("span");
          node.className = className;
          node.dataset.entityId = String(card.entity_id);
          node.textContent = card.name;
          return node;
        }));
      }
    } };
    adapter.commit(initial);
    const start = performance.now();
    await presentation.play([frame], final, adapter, () => true, {
      maxPlaybackMs: 50, beforeFinal: () => { resumed = true; },
    });
    const bounded = { elapsed: performance.now() - start, finalCommits, resumed,
      finalRestored: current === final, notice: notice.textContent,
      tailDeathAnimated: motions.some(motion => motion.id === victim.entity_id && motion.ghost &&
        motion.frames.at(-1).opacity === 0),
      tailDrawAnimated: motions.some(motion => motion.id === drawn.entity_id && motion.hand &&
        motion.frames[0].opacity === 0) };
    adapter.commit(initial);
    finalCommits = 0;
    const pending = presentation.play([frame], final, adapter, () => true);
    window.setTimeout(() => presentation.cancel(), 50);
    await pending;
    await new Promise(resolve => window.setTimeout(resolve, 700));
    const temporaryCount = document.querySelectorAll('.presentation-effect-caption, .presentation-effect-anchor, .presentation-number, .presentation-ghost, .presentation-bolt').length;
    Element.prototype.animate = previousAnimate;
    board.remove();
    hand.remove();
    return { ...bounded, cancelledFinalCommits: finalCommits, temporaryCount };
  });
  assert(result.elapsed < 3000, "A long chain must respect its playback time budget");
  assert.equal(result.finalCommits, 1);
  assert.equal(result.finalRestored, true);
  assert.equal(result.resumed, true, "Fast-forward must release the input lock");
  assert.equal(result.tailDeathAnimated, true, "Fast-forward must reconcile deaths in the skipped tail");
  assert.equal(result.tailDrawAnimated, true, "Fast-forward must preserve draws in the skipped tail");
  assert.equal(result.notice, "PRESENTATION_FAST_FORWARD");
  assert.equal(result.cancelledFinalCommits, 0, "Cancelled playback must not commit a stale final result");
  assert.equal(result.temporaryCount, 0, "Cancelled playback must stop creating temporary visuals");
}

async function checkEventLogCache(page) {
  const result = await page.evaluate(async () => {
    const { createDecisions } = await import("/gui_decisions.js");
    const log = document.createElement("ol");
    log.id = "synthetic-event-log";
    document.body.appendChild(log);
    const current = {
      latestEventSeq: 9,
      snapshot: { session_id: "log-cache-session-a", observation: { self: {}, opponent: {} } },
    };
    const state = { current };
    const data = {
      asArray: value => Array.isArray(value) ? value : [],
      safeNumber: (value, fallback) => Number.isFinite(value) ? value : fallback,
      safeText: (value, fallback) => value === undefined || value === null ? fallback : String(value),
      entityId: value => Number.isSafeInteger(Number(value)) ? Number(value) : null,
      isObject: value => Boolean(value) && typeof value === "object" && !Array.isArray(value),
      labelForType: value => String(value),
      cardName: card => card.name,
    };
    const locale = {
      locale: "enUS",
      tr: (key, variables) => locale.locale + ":" + key +
        (variables && variables.source ? ":" + variables.source : ""),
    };
    const decisions = createDecisions({
      document, elements: { "event-log": log }, state, model: {}, data,
      dom: { clear: node => node.replaceChildren() }, locale, cards: {},
      onRender() {}, onSubmitAction() {}, onLoadState() {}, getBusy: () => false,
    });
    const events = [{ seq: 9, type: "PLAY_CARD", actor: "self", source_entity_id: 123,
      source_name: "Synthetic card" }];
    let animationStarts = 0;
    log.addEventListener("animationstart", event => {
      if (event.animationName === "event-in" && event.target.matches(".event-item.latest")) animationStarts += 1;
    });
    const waitForIntro = () => new Promise(resolve => setTimeout(resolve, 280));
    decisions.renderLog(events);
    const firstNode = log.querySelector(".event-item.latest");
    await waitForIntro();
    const initialStarts = animationStarts;

    log.replaceChildren();
    decisions.renderLog(events);
    const restoredNode = log.querySelector(".event-item.latest");
    const restored = Boolean(restoredNode && restoredNode === firstNode &&
      restoredNode.dataset.eventSeq === "9");
    await waitForIntro();
    const afterExternalClear = animationStarts;

    locale.locale = "zhCN";
    decisions.renderLog(events);
    const localizedNode = log.querySelector(".event-item.latest");
    const localizedText = localizedNode?.textContent || "";
    await waitForIntro();
    const afterLocaleChange = animationStarts;

    current.snapshot.session_id = "log-cache-session-b";
    decisions.renderLog(events);
    const newSessionNode = log.querySelector(".event-item.latest");
    const resetForSession = Boolean(newSessionNode && newSessionNode !== firstNode);
    await waitForIntro();
    const afterNewSession = animationStarts;
    log.remove();
    return { initialStarts, afterExternalClear, afterLocaleChange, afterNewSession,
      restored, resetForSession, localizedText };
  });
  assert.equal(result.initialStarts, 1, "A new public event should animate its latest row once");
  assert.equal(result.restored, true, "An externally cleared event log should restore cached rows");
  assert.equal(result.afterExternalClear, 1, "Restoring unchanged events must not replay the intro");
  assert.equal(result.localizedText.startsWith("zhCN:"), true, "A locale change must refresh cached row text");
  assert.equal(result.afterLocaleChange, 1, "Changing locale must not replay the latest-row intro");
  assert.equal(result.resetForSession, true, "A new session must not reuse stale event nodes");
  assert.equal(result.afterNewSession, 2, "The same event sequence in a new session should animate once again");
}

async function runScenario(browser, scenario, reducedMotion = "no-preference") {
  const server = fixture(scenario);
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, reducedMotion });
  const errors = [];
  try {
    const url = await server.ready;
    await context.route("**/api/account/session", route => route.fulfill({ status: 200,
      contentType: "application/json", body: JSON.stringify({ authenticated: true,
        account: { id: "effect-fixture", username: "Animation tester" }, legacy_available: false }) }));
    await context.route("**/assets/**", route => route.fulfill({ status: 404, body: "" }));
    await context.route("**/api/decks*", route => route.fulfill({ status: 200,
      contentType: "application/json", body: JSON.stringify({ decks: [] }) }));
    await context.route("**/favicon.ico", route => route.fulfill({ status: 204, body: "" }));
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(String(error)));
    page.on("console", message => {
      if (message.type() === "error" && !(message.text().includes("404") &&
          new URL(message.location().url || url).pathname.startsWith("/assets/"))) errors.push(message.text());
    });
    await page.goto(url);
    await page.getByTestId("action-submit").waitFor({ state: "visible" });
    await submitFromUi(page, () => page.getByTestId("action-submit").click());
    const opening = await state(page);
    const sourceCardId = {
      battlecry: "CS2_189", reflow: "CS2_189", chain: "CS2_032",
      draw: "EX1_015", depletion: "CS2_023", elysiana: "DAL_736",
    }[scenario];
    const sourceId = sourceCardId
      ? opening.observation.self.hand.find(card => card.card_id === sourceCardId).entity_id
      : scenario === "combat"
        ? opening.observation.self.board.find(card => card.card_id === "CS2_182").entity_id
      : scenario.startsWith("hero_combat")
        ? opening.observation.self.hero.entity_id
      : opening.observation.self.hero_power.entity_id;
    const targetId = ["hero_power", "hero_combat_hero"].includes(scenario)
      ? opening.observation.opponent.hero.entity_id
      : ["battlecry", "reflow"].includes(scenario)
        ? opening.observation.opponent.board.find(card => card.card_id === "FP1_002").entity_id
        : ["draw", "depletion", "elysiana"].includes(scenario) ? null
          : opening.observation.opponent.board.find(card => card.card_id ===
            (scenario === "hero_combat" ? "CS2_182" : "GVG_076")).entity_id;
    if (["battlecry", "reflow"].includes(scenario)) {
      await page.locator('.hand-card[data-entity-id="' + sourceId + '"]').click();
      await page.locator('.board-slot[data-position="0"]').click();
    }
    await traceEffects(page);
    const latestText = async () => {
      const latest = page.locator("#event-log .event-item.latest");
      return await latest.count() ? latest.textContent() : null;
    };
    const latestActions = [{ before: await latestText(), payload: null, after: null }];
    const fatigueScreenshot = scenario === "depletion"
      ? page.waitForFunction(() => {
        const cue = document.querySelector('[data-effect-type="FATIGUE"]');
        return cue && Number(getComputedStyle(cue).opacity) > 0.6 &&
          cue.getBoundingClientRect().width > 0;
      }, null, { timeout: 60000 }).then(() =>
        page.screenshot({ path: path.join(artifacts, "depletion-" + reducedMotion + "-fatigue.png") }))
      : null;
    const payload = await submitFromUi(page, async () => {
      if (["battlecry", "reflow"].includes(scenario)) {
        await page.locator('.targetable[data-entity-id="' + targetId + '"]').click();
      } else if (scenario === "combat" || scenario.startsWith("hero_combat")) {
        await page.locator((scenario === "combat" ? '#self-board .board-card' : '#self-hero-row .hero-card') +
          '[data-entity-id="' + sourceId + '"]').click();
        await page.locator('.targetable[data-entity-id="' + targetId + '"]').click();
      } else if (scenario === "hero_power") {
        await page.locator('.power-card[data-entity-id="' + sourceId + '"]').click();
        await page.locator('.targetable[data-entity-id="' + targetId + '"]').click();
      } else {
        await page.locator('.hand-card[data-entity-id="' + sourceId + '"]').click();
        if (["draw", "elysiana"].includes(scenario)) {
          await page.locator('.board-slot[data-position="0"]').click();
        }
      }
    }, reducedMotion === "no-preference" && ["battlecry", "chain", "reflow"].includes(scenario) ? scenario : null);
    if (fatigueScreenshot) await fatigueScreenshot;
    latestActions[0].payload = payload;
    latestActions[0].after = await latestText();
    assertPublicEffects(payload);
    const payloads = [payload];
    const fatigueActionChecks = [];
    if (scenario === "elysiana") {
      const initialEffects = payload.presentation_steps.flatMap(frame => frame.effects || []);
      const deckDestroy = initialEffects.filter(effect => effect.event.type === "DECK_DESTROY");
      assert.equal(deckDestroy.length, 1, "Elysiana must emit one coalesced deck destruction effect");
      assert.equal(deckDestroy[0].event.amount > 10, true,
        "Elysiana fixture must destroy more than ten deck cards");
      assert(!Object.keys(deckDestroy[0].event).some(key => key.startsWith("target")),
        "Deck destruction must not expose a formerly public target");
      assert.equal(initialEffects.filter(effect => effect.event.type === "DESTROY").length, 0,
        "Elysiana must not emit one destroy effect per hidden deck card");
      assert.equal(payload.observation.self.deck_count, 0,
        "Elysiana must empty the old deck before choices rebuild it");
      for (let index = 0; index < 5; index += 1) {
        const beforeChoice = await state(page);
        const choice = beforeChoice.legal_actions.find(action => action.type === "CHOOSE");
        assert(choice, "Elysiana choice " + (index + 1) + " must be available");
        const next = await submitFromUi(page, async () => {
          await page.locator('#choice-options [role="button"]').first().click();
        });
        assertPublicEffects(next);
        payloads.push(next);
      }
      const rebuilt = await state(page);
      assert.equal(rebuilt.observation.self.deck_count, 10,
        "All five Elysiana choices must rebuild a ten-card deck");
    }
    const firstActionTrace = scenario === "depletion"
      ? await page.evaluate(() => window.__effectTrace.slice())
      : null;
    if (scenario === "depletion") {
      const drawn = payload.observation.self.hand.find(card =>
        !opening.observation.self.hand.some(old => old.entity_id === card.entity_id));
      assert(drawn, "Arcane Intellect must draw the last card from the deck");
      assert.equal(drawn.card_id, "CS2_231", "The only deck card must enter the hand");
      assert.equal(payload.observation.self.deck_count, 0, "Arcane Intellect must empty the deck");
      assert.equal(payload.observation.self.hero.health, opening.observation.self.hero.health - 1,
        "The first empty-deck draw must deal exactly one fatigue damage");
      for (const [index, fatigueAmount] of [2, 3].entries()) {
        const beforeAction = await state(page);
        const engineer = beforeAction.observation.self.hand.find(card => card.card_id === "EX1_015");
        assert(engineer, "Fatigue follow-up " + fatigueAmount + " needs Novice Engineer in hand");
        const effectCursor = await page.evaluate(() => window.__effectTrace.length);
        const handCursor = await page.evaluate(() => window.__handEntrances.length);
        const eventAction = { before: await latestText(), payload: null, after: null };
        const next = await submitFromUi(page, async () => {
          await page.locator('.hand-card[data-entity-id="' + engineer.entity_id + '"]').click();
          await page.locator('#self-board .board-slot[data-position="' + index + '"]').click();
        });
        eventAction.payload = next;
        eventAction.after = await latestText();
        latestActions.push(eventAction);
        assertPublicEffects(next);
        payloads.push(next);
        const handAfter = next.observation.self.hand;
        assert.equal(handAfter.length, beforeAction.observation.self.hand.length - 1,
          "Fatigue " + fatigueAmount + " must not create a fake hand draw");
        assert(handAfter.every(card => beforeAction.observation.self.hand.some(old => old.entity_id === card.entity_id)),
          "Fatigue " + fatigueAmount + " must not add a new hand entity");
        assert.equal(next.observation.self.deck_count, 0);
        assert.equal(next.observation.self.hero.health,
          beforeAction.observation.self.hero.health - fatigueAmount,
          "Fatigue " + fatigueAmount + " must damage the hero by its counter value");
        const newEffects = await page.evaluate(cursor => window.__effectTrace.slice(cursor), effectCursor);
        const newEntrances = await page.evaluate(cursor => window.__handEntrances.slice(cursor), handCursor);
        assert.equal(newEffects.filter(item => item.type === "FATIGUE").length, 1,
          "Fatigue " + fatigueAmount + " must render one fatigue cue");
        const damageLabels = newEffects.filter(item => item.type === "DAMAGE" &&
          item.target === opening.observation.self.hero.entity_id &&
          item.className.split(/\s+/).includes("presentation-number"));
        assert.equal(damageLabels.length, 1,
          "Fatigue " + fatigueAmount + " must render one numeric hero damage");
        assert.match(damageLabels[0].text, new RegExp("[−-]" + fatigueAmount));
        assert.equal(newEffects.filter(item => item.type === "DECK_EMPTY").length, 0,
          "An already empty deck must not replay the deck-empty cue");
        assert.equal(newEntrances.length, 0,
          "Fatigue " + fatigueAmount + " must not animate a nonexistent card entering the hand");
        const actionEffects = next.presentation_steps.flatMap(frame => frame.effects || []);
        assert.equal(actionEffects.filter(effect => effect.event.type === "FATIGUE" &&
          effect.event.amount === fatigueAmount).length, 1,
        "The fatigue " + fatigueAmount + " telemetry must appear once");
        assert.equal(actionEffects.filter(effect => effect.event.type === "DAMAGE" &&
          effect.event.target_entity_id === opening.observation.self.hero.entity_id &&
          effect.event.amount === fatigueAmount).length, 1,
        "The hero must receive one damage record for fatigue " + fatigueAmount);
        fatigueActionChecks.push({ fatigueAmount, effects: newEffects });
        assert.equal(await page.locator(".presentation-ghost, .presentation-number, .presentation-effect-caption, .presentation-effect-anchor, .presentation-bolt").count(), 0,
          "Fatigue " + fatigueAmount + " playback must clean up before the next action");
      }
    }
    const effectCount = payloads.reduce((sum, item) =>
      sum + item.presentation_steps.flatMap(frame => frame.effects || []).length, 0);
    assert(effectCount, "Real engine response must include effect records");
    await page.evaluate(() => new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const effects = payload.presentation_steps.flatMap(frame => frame.effects || []);
    const trace = await page.evaluate(() => window.__effectTrace);
    const instrumentation = await stopTraceEffects(page);
    for (const eventAction of latestActions) {
      assertLatestEventAnimatedOnce(instrumentation.latestEventStarts,
        eventAction.after, eventAction.before, eventAction.payload);
    }
    if (["battlecry", "reflow"].includes(scenario)) {
      before(trace, "DAMAGE", "DEATH", targetId);
      assert(trace.some(item => item.type === "DAMAGE" && item.target === targetId && /[−-]\d/.test(item.text)),
        "A lethally damaged minion must show its damage amount");
      assert(trace.some(item => item.type === "DEATHRATTLE" && item.source === targetId && item.rendered),
        "Dead source must still have a rendered deathrattle cue");
    }
    if (scenario === "battlecry") {
      assert(trace.some(item => item.type === "BATTLECRY" && item.source === sourceId && item.rendered));
      assert.equal(payload.observation.opponent.board.length, 2, "Creeper must leave two tokens");
    } else if (scenario === "reflow") {
      const survivorId = opening.observation.opponent.board.find(card => card.card_id === "CS2_182").entity_id;
      const positions = instrumentation.boardPositions.filter(item => item.id === survivorId);
      assert(positions.length > 1, "The surviving Yeti must be observed across intermediate board commits");
      assert(!positions.at(-1).ids.includes(targetId), "The Creeper must be gone in the final observed board");
      assert(Math.abs(positions[0].left - positions.at(-1).left) > 1,
        "The surviving Yeti must shift when Creeper leaves the board");
      const motions = instrumentation.boardMotions.filter(item => item.id === survivorId);
      for (const motion of motions) {
        const previousPosition = positions.filter(item => item.time < motion.time).at(-1);
        if (!previousPosition) continue;
        assert(Math.abs(motion.startLeft - previousPosition.left) <= 2,
          "Yeti reflow must begin at its immediately committed position: motion=" +
          JSON.stringify(motion) + " previous=" + JSON.stringify(previousPosition));
      }
    } else if (scenario === "elysiana") {
      assert.equal(trace.filter(item => item.type === "DECK_DESTROY").length, 1,
        "Elysiana must show one deck destruction cue");
      assert.equal(trace.filter(item => item.type === "DESTROY").length, 0,
        "Elysiana must not show per-card destroy cues");
      assert.equal(trace.filter(item => item.type === "DECK_EMPTY").length, 0,
        "Elysiana must not duplicate deck-empty for the destruction cue");
    } else if (scenario === "combat" || scenario.startsWith("hero_combat")) {
      const directDamage = effects.filter(effect => effect.event.type === "DAMAGE" &&
        effect.event.combat_damage === true);
      const triggerDamage = effects.filter(effect => effect.event.type === "DAMAGE" &&
        effect.event.combat_damage !== true &&
        effect.event.source_entity_id !== effect.event.target_entity_id);
      assert(directDamage.length >= 1, "Combat must tag normal attack damage");
      if (["combat", "hero_combat_trigger"].includes(scenario)) {
        assert(triggerDamage.length >= 1, "Combat deathrattle damage must remain a trigger");
      }
      assert.equal(instrumentation.projectiles.length, triggerDamage.length,
        "Only attack-time trigger damage may create projectiles");
      if (scenario.startsWith("hero_combat")) {
        if (scenario === "hero_combat_hero") {
          assert.equal(payload.observation.self.weapon, null,
            "The last durability must destroy Perdition's Blade");
          assert.equal(payload.observation.opponent.hero.armor, 1,
            "Hero combat must consume armor before health");
        } else {
          assert.equal(payload.observation.self.weapon.durability,
            opening.observation.self.weapon.durability - 1, "Hero attack must consume one durability");
        }
        assert.equal(payload.observation.self.hero.health,
          opening.observation.self.hero.health - (scenario === "hero_combat" ? 4 : scenario === "hero_combat_trigger" ? 1 : 0),
          "Hero must receive the normal retaliation damage");
      }
    } else if (scenario === "draw") {
      const trigger = trace.find(item => item.type === "BATTLECRY" && item.source === sourceId && item.rendered);
      assert(trigger, "Engineer must show its battlecry cue");
      const drawn = payload.observation.self.hand.find(card =>
        !opening.observation.self.hand.some(old => old.entity_id === card.entity_id));
      assert(drawn, "Engineer must draw a new card");
      const entrances = await page.evaluate(() => window.__handEntrances);
      assert.equal(entrances.filter(entry => entry.id === drawn.entity_id).length, 1,
        "A battlecry draw must animate its new hand card exactly once");
      assert(entrances.find(entry => entry.id === drawn.entity_id).time >= trigger.time,
        "The card draw must follow its battlecry cue");
      await checkLongChainAndCancellation(page);
      await checkEventLogCache(page);
    } else if (scenario === "chain") {
      const abomination = opening.observation.self.board.find(card => card.card_id === "EX1_097").entity_id;
      const yeti = opening.observation.self.board.find(card => card.card_id === "CS2_182").entity_id;
      before(trace, "DAMAGE", "DEATH", abomination);
      before(trace, "DAMAGE", "DEATH", yeti);
      const sheepTrigger = trace.findIndex(item => item.type === "DEATHRATTLE" && item.source === targetId);
      const abomTrigger = trace.findIndex(item => item.type === "DEATHRATTLE" && item.source === abomination);
      assert(sheepTrigger >= 0 && abomTrigger > sheepTrigger, "Chain deathrattles must appear in engine order");
      const victimIds = opening.observation.opponent.board.map(card => card.entity_id);
      for (const victim of victimIds) {
        before(trace, "DAMAGE", "DEATH", victim);
        assert(trace.findIndex(item => item.type === "DEATH" && item.target === victim) < sheepTrigger,
          "Every member of the simultaneous death wave must retire before its deathrattles");
      }
      assert(trace.some(item => item.type === "DAMAGE" && victimIds.every(id => item.concurrentDamage.includes(id))),
        "Flamestrike damage numbers must coexist for the entire enemy wave");
      assert.equal(payload.observation.self.board.length, 0);
      assert.equal(payload.observation.opponent.board.length, 0);
    } else if (scenario === "hero_power") {
      const heroDamage = trace.filter(item => item.type === "DAMAGE" && item.target === targetId &&
        item.className.split(/\s+/).includes("presentation-number"));
      assert.equal(heroDamage.length, 1, "Fireblast must create one numeric damage result on its selected hero");
      assert.match(heroDamage[0].text, /[−-]1/);
      assert.equal(instrumentation.projectiles.length, 1,
        "Fireblast must fly one projectile total across intent and DAMAGE presentation: " +
        JSON.stringify(instrumentation.projectiles));
      assert.equal(payload.observation.opponent.hero.health, opening.observation.opponent.hero.health - 1);
    } else if (scenario === "depletion") {
      const selfHeroId = opening.observation.self.hero.entity_id;
      const fatigueEvents = effects.filter(effect => effect.event.type === "FATIGUE");
      const damageEvents = effects.filter(effect => effect.event.type === "DAMAGE" &&
        effect.event.target_entity_id === selfHeroId);
      assert.equal(fatigueEvents.length, 1, "The first empty-deck draw must emit one fatigue record");
      assert.equal(fatigueEvents[0].event.amount, 1);
      assert.equal(damageEvents.length, 1, "The first empty-deck draw must emit one hero damage record");
      assert.equal(damageEvents[0].event.amount, 1);
      assert.equal(trace.filter(item => item.type === "DECK_EMPTY").length, 1,
        "A public deck-count transition to zero must show one deck-empty cue");
      const deckEmptyCue = firstActionTrace.find(item => item.type === "DECK_EMPTY");
      const firstFatigueCue = firstActionTrace.find(item => item.type === "FATIGUE" && item.target === selfHeroId);
      assert(deckEmptyCue && firstFatigueCue, "The first action must show both deck-empty and fatigue cues");
      assert(deckEmptyCue.time < firstFatigueCue.time,
        "The deck-empty cue must finish before the first fatigue cue starts");
      assert.equal(firstFatigueCue.overlappingDeckEmpty, 0,
        "Deck-empty and fatigue captions must not overlap");
      for (const cue of [deckEmptyCue, firstFatigueCue]) {
        assert.equal(cue.rendered, true, "Deck and fatigue cues must be rendered");
        assert.equal(cue.withinViewport, true,
          "Deck and fatigue cues must fit in the 1366×900 viewport: " + JSON.stringify(cue));
      }
      const firstFatigueDamage = firstActionTrace.filter(item => item.type === "DAMAGE" &&
        item.target === selfHeroId && item.className.split(/\s+/).includes("presentation-number"));
      assert.equal(firstFatigueDamage.length, 1, "The first fatigue tick must show one numeric hero damage");
      assert.match(firstFatigueDamage[0].text, /[−-]1/);
      const allFatigueCues = trace.filter(item => item.type === "FATIGUE" && item.target === selfHeroId);
      assert.equal(allFatigueCues.length, 3, "Each fatigue counter must show one cue");
      const damageTexts = [
        firstFatigueDamage[0].text,
        ...fatigueActionChecks.flatMap(check => check.effects
          .filter(item => item.type === "DAMAGE" && item.target === selfHeroId &&
            item.className.split(/\s+/).includes("presentation-number"))
          .map(item => item.text)),
      ];
      assert.deepEqual(damageTexts.map(text => (text.match(/\d+/) || [])[0]), ["1", "2", "3"],
        "The three fatigue ticks must each show their matching numeric damage once");
      const handEntrances = await page.evaluate(() => window.__handEntrances);
      const drawn = payload.observation.self.hand.find(card =>
        !opening.observation.self.hand.some(old => old.entity_id === card.entity_id));
      assert.equal(handEntrances.filter(entry => entry.id === drawn.entity_id).length, 1,
        "The final real card must animate into hand exactly once");
      for (const check of fatigueActionChecks) {
        assert.equal(check.effects.filter(item => item.type === "FATIGUE").length, 1);
      }
    }
    const actual = await state(page);
    assert.equal(actual.revision, payloads.at(-1).revision);
    assert.equal(await page.getByTestId("end-turn-button").isEnabled(), true,
      "Input must become available after animation playback");
    assert.equal(await page.locator(".presentation-ghost, .presentation-number, .presentation-effect-caption, .presentation-effect-anchor, .presentation-bolt").count(), 0,
      "Playback must clean up temporary visuals");
    assert.deepEqual(errors, [], "Effect playback must not fail or fall back silently");
    await page.screenshot({ path: path.join(artifacts, `${scenario}-${reducedMotion}-final.png`) });
    return { scenario, reducedMotion, effectCount,
      visualTypes: [...new Set(trace.map(item => item.type))], result: "PASS" };
  } finally {
    await context.close();
    server.child.kill("SIGINT");
    await new Promise(resolve => server.child.exitCode !== null ? resolve() : server.child.once("exit", resolve));
  }
}

(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/opt/google/chrome/chrome",
    headless: true, args: ["--no-sandbox"] });
  try {
    const scenarios = process.env.EFFECT_SCENARIOS
      ? process.env.EFFECT_SCENARIOS.split(",").filter(Boolean)
      : process.env.EFFECT_REDUCED_SCENARIOS ? []
      : ["battlecry", "chain", "combat", "hero_combat", "hero_combat_trigger", "hero_combat_hero", "draw", "elysiana", "hero_power", "reflow", "depletion"];
    for (const scenario of scenarios) {
      console.log(JSON.stringify(await runScenario(browser, scenario)));
    }
    if (!process.env.EFFECT_SCENARIOS) {
    const reducedScenarios = process.env.EFFECT_REDUCED_SCENARIOS
      ? process.env.EFFECT_REDUCED_SCENARIOS.split(",").filter(Boolean)
      : process.env.EFFECT_SCENARIOS ? [] : ["chain", "depletion"];
    for (const scenario of reducedScenarios) {
      console.log(JSON.stringify(await runScenario(browser, scenario, "reduce")));
    }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
