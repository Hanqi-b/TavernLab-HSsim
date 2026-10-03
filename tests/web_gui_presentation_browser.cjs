#!/usr/bin/env node
/* Real-Chrome presentation acceptance for pointer drag and AI action frames. */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixturePath = path.join(__dirname, "web_gui_browser_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-web-gui-artifacts");
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);

function startFixture() {
  const child = spawn(python, ["-u", fixturePath, "--seed", "1701", "--port", "0"], {
    cwd: root,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  const lines = readline.createInterface({ input: child.stdout });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`fixture startup timed out\n${logs.join("")}`)), 30000);
    lines.on("line", (line) => {
      logs.push(`${line}\n`);
      try {
        const value = JSON.parse(line);
        if (value && typeof value.url === "string") {
          clearTimeout(timer);
          resolve(value);
        }
      } catch (_error) { /* ignore startup diagnostics */ }
    });
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      reject(new Error(`fixture exited before ready (code=${code}, signal=${signal})\n${logs.join("")}`));
    });
  });
  return { child, ready };
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function sameAction(left, right) {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

async function stateFromPage(page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`GET /api/state failed: ${response.status}`);
    return response.json();
  });
}

async function waitForIdle(page) {
  await page.waitForFunction(() => window.fireplaceWebGui &&
    typeof window.fireplaceWebGui.isBusy === "function" && !window.fireplaceWebGui.isBusy(), null, { timeout: 60000 });
}

async function beginRevisionTrace(page) {
  await page.evaluate(() => {
    const read = () => Number(document.querySelector('[data-testid="revision"]')?.textContent.match(/(\d+)/)?.[1] || 0);
    const trace = { active: true, last: read(), revisions: [read()] };
    window.__presentationRevisionTrace = trace;
    const record = () => {
      const value = read();
      if (value !== trace.last) {
        trace.revisions.push(value);
        trace.last = value;
      }
    };
    const observer = new MutationObserver(record);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    window.__presentationRevisionObserver = observer;
  });
}

async function endRevisionTrace(page) {
  return page.evaluate(() => {
    const trace = window.__presentationRevisionTrace;
    if (!trace) return [];
    trace.active = false;
    window.__presentationRevisionObserver?.disconnect();
    window.__presentationRevisionObserver = null;
    return trace.revisions.slice();
  });
}

function assertDisplayedFrames(before, payload, revisions, label) {
  const displayed = revisions.slice(1);
  assert(displayed.every((revision, index) => index === 0 || revision > displayed[index - 1]),
    `${label}: displayed revisions must increase strictly: ${JSON.stringify(displayed)}`);
  const actionFrames = (payload.presentation_steps || []).filter((frame) =>
    frame.revision > before.revision &&
    ["PLAY_CARD", "ATTACK", "USE_HERO_POWER", "END_TURN"].includes(frame.event?.type));
  const missing = actionFrames.map((frame) => frame.revision).filter((revision) => !displayed.includes(revision));
  assert.deepEqual(missing, [], `${label}: every Action presentation frame must appear in DOM revision order; ` +
    JSON.stringify({ missing, displayed, actionFrames: actionFrames.map((frame) => ({ revision: frame.revision, event: frame.event })) }));
  assert(displayed.includes(payload.revision),
    `${label}: final response revision ${payload.revision} must be displayed; got ${JSON.stringify(displayed)}`);
}

function assertFinalSnapshotDisplayed(before, payload, revisions, label) {
  const displayed = revisions.slice(1);
  assert(displayed.every((revision, index) => index === 0 || revision > displayed[index - 1]),
    `${label}: displayed revisions must increase strictly: ${JSON.stringify(displayed)}`);
  assert(displayed.includes(payload.revision),
    `${label}: final response revision ${payload.revision} must be displayed; got ${JSON.stringify(displayed)}`);
}

async function sendFromUi(page, before, operation, label) {
  const requestPromise = page.waitForRequest((request) => request.method() === "POST" &&
    new URL(request.url()).pathname === "/api/action", { timeout: 60000 });
  const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/action", { timeout: 60000 });
  await operation();
  const request = await requestPromise;
  const body = request.postDataJSON();
  assert.equal(body.session_id, before.session_id, `${label}: session id must be current`);
  assert.equal(body.revision, before.revision, `${label}: submitted revision must be current`);
  assert(before.legal_actions.some((action) => sameAction(action, body.action)),
    `${label}: submitted action must exactly match a legal action: ${JSON.stringify(body.action)}`);
  const response = await responsePromise;
  const payload = await response.json();
  assert.equal(response.status(), 200, `${label}: ${JSON.stringify(payload)}`);
  await waitForIdle(page);
  await page.waitForFunction((revision) => {
    const value = Number(document.querySelector('[data-testid="revision"]')?.textContent.match(/(\d+)/)?.[1] || 0);
    return value >= revision;
  }, payload.revision, { timeout: 60000 });
  return { action: body.action, payload };
}

async function dragFromHand(page, locator, chooseDestination, pageErrors = []) {
  await locator.waitFor({ state: "visible", timeout });
  const pointOnCard = async () => locator.evaluate((card) => {
    const rect = card.getBoundingClientRect();
    const vertical = [.88, .8, .72, .64, .56, .48, .4, .32, .24, .16];
    const horizontal = [.08, .16, .24, .32, .4, .48, .56, .64, .72, .8, .88, .92];
    for (const fy of vertical) for (const fx of horizontal) {
      const x = rect.left + rect.width * fx;
      const y = rect.top + rect.height * fy;
      const target = document.elementFromPoint(x, y);
      if (target?.closest(".hand-card") === card && !target.closest(".card-inspect")) return { x, y };
    }
    return null;
  });
  let origin = await pointOnCard();
  assert(origin, "hand card must expose a draggable point outside its inspect control");
  await page.mouse.move(origin.x, origin.y);
  await page.waitForTimeout(150);
  origin = await pointOnCard();
  assert(origin, "hovered hand card must retain a draggable hit-test point");
  const originBox = await locator.boundingBox();
  assert(originBox, "hovered hand card should have a visible box");
  await page.mouse.move(origin.x, origin.y);
  await page.evaluate(() => {
    window.__handDragPointerLog = [];
    if (window.__handDragPointerLogging) return;
    window.__handDragPointerLogging = true;
    for (const type of ["pointerdown", "pointermove", "pointerup", "pointercancel", "lostpointercapture", "dragstart", "dragend"]) {
      document.addEventListener(type, (event) => {
        const target = event.target?.closest?.("[data-entity-id]");
        window.__handDragPointerLog.push({ type, x: event.clientX, y: event.clientY,
          pointerId: event.pointerId, pointerType: event.pointerType, isPrimary: event.isPrimary, button: event.button,
          targetTag: event.target?.tagName || null, draggable: Boolean(event.target?.draggable),
          targetClass: String(event.target?.className || ""),
          entityId: target?.getAttribute("data-entity-id") || null });
        if (window.__handDragPointerLog.length > 40) window.__handDragPointerLog.shift();
      }, true);
    }
  });
  await page.mouse.down();
  await page.mouse.move(origin.x + 12, origin.y + 8, { steps: 2 });
  try {
    await page.locator(".hand-drag-ghost").waitFor({ state: "visible", timeout: 3000 });
  } catch (error) {
    const debug = await page.evaluate((point) => {
      const target = document.elementFromPoint(point.x, point.y);
      const card = target?.closest?.(".hand-card");
      const rect = card?.getBoundingClientRect();
      return { isBusy: window.fireplaceWebGui?.isBusy?.(),
        hit: { className: String(target?.className || ""),
          entityId: target?.closest?.("[data-entity-id]")?.getAttribute("data-entity-id") || null,
          inspect: Boolean(target?.closest?.(".card-inspect")) },
        card: card && { className: card.className, entityId: card.getAttribute("data-entity-id"),
          rect: rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height } },
        handActive: document.querySelector("#hand")?.className,
        pointerEvents: window.__handDragPointerLog || [] };
    }, origin);
    throw new Error("hand drag ghost did not appear; origin=" + JSON.stringify(origin) +
      "; cardBox=" + JSON.stringify(originBox) + "; debug=" + JSON.stringify(debug) +
      "; pageErrors=" + JSON.stringify(pageErrors) + "; cause=" + error.message);
  }
  const trackingPoint = { x: origin.x + 48, y: origin.y - 42 };
  await page.mouse.move(trackingPoint.x, trackingPoint.y, { steps: 5 });
  const tracking = await page.locator(".hand-drag-ghost").boundingBox();
  assert(tracking, "drag ghost should remain visible while pointer moves");
  const trackingCenter = { x: tracking.x + tracking.width / 2, y: tracking.y + tracking.height / 2 };
  const expectedGhostCenter = { x: originBox.x + originBox.width / 2 + trackingPoint.x - origin.x,
    y: originBox.y + originBox.height / 2 + trackingPoint.y - origin.y };
  assert(Math.hypot(trackingCenter.x - expectedGhostCenter.x, trackingCenter.y - expectedGhostCenter.y) < 14,
    `drag ghost should follow the pointer continuously: ${JSON.stringify({ trackingCenter, expectedGhostCenter })}`);
  const destination = typeof chooseDestination === "function" ? await chooseDestination() : chooseDestination;
  assert(destination && Number.isFinite(destination.x) && Number.isFinite(destination.y),
    "drag destination must be resolved after drag feedback appears");
  await page.mouse.move(destination.x, destination.y, { steps: 12 });
  return { originBox, origin, trackingPoint, destination };
}

async function captureEndTurn(page, before, label, consoleErrors = []) {
  await beginRevisionTrace(page);
  const result = await sendFromUi(page, before, () => page.locator("#end-turn-button").click(), label);
  const revisions = await endRevisionTrace(page);
  try {
    assertDisplayedFrames(before, result.payload, revisions, label);
  } catch (error) {
    const diagnostic = await page.evaluate(() => ({
      revision: document.querySelector('[data-testid="revision"]')?.textContent,
      busy: window.fireplaceWebGui?.isBusy?.(),
      animations: window.__presentationAnimations || [],
      ghosts: document.querySelectorAll(".presentation-ghost").length,
      turnBanners: document.querySelectorAll(".presentation-turn").length,
      notice: document.querySelector("#notice")?.textContent,
    }));
    throw new Error(error.message + "\nconsoleErrors=" + JSON.stringify(consoleErrors) +
      "\npresentationDiagnostic=" + JSON.stringify(diagnostic));
  }
  return { ...result, revisions };
}

async function stopFixture(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function main() {
  fs.mkdirSync(artifacts, { recursive: true });
  const fixture = startFixture();
  let browser;
  let context;
  try {
    const endpoint = await fixture.ready;
    browser = await chromium.launch({
      headless: process.env.FIREPLACE_GUI_HEADFUL !== "1",
      executablePath: chrome,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({
        authenticated: true,
        account: { id: "fixture-account", username: "Fixture" },
        legacy_available: false,
      }),
    }));
    await context.addInitScript(() => {
      const original = Element.prototype.animate;
      window.__presentationAnimations = [];
      if (typeof original === "function") {
        Element.prototype.animate = function (keyframes, options) {
          const className = typeof this.className === "string" ? this.className : this.className?.baseVal || "";
          window.__presentationAnimations.push({ className, duration: options?.duration || 0,
            effectType: this.dataset?.effectType || null,
            targetEntityId: Number(this.dataset?.targetEntityId || 0),
          });
          return original.call(this, keyframes, options);
        };
      }
    });

    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const pageErrors = [];
    const consoleErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.stack || String(error)));
    page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
    const actionRequests = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === "/api/action") {
        actionRequests.push(request.postDataJSON());
      }
    });
    await page.goto(endpoint.url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelector('[data-testid="phase"]')?.textContent.trim() === "换牌", null, { timeout });

    let before = await stateFromPage(page);
    await beginRevisionTrace(page);
    const mulligan = await sendFromUi(page, before, () => page.locator("#action-submit").click(), "Mulligan");
    const mulliganRevisions = await endRevisionTrace(page);
    assertFinalSnapshotDisplayed(before, mulligan.payload, mulliganRevisions, "Mulligan");
    before = await stateFromPage(page);
    assert.equal(before.observation.phase, "MAIN");

    const wisp = before.observation.self.hand.find((card) => card.card_id === "CS2_231");
    assert(wisp, "showcase hand must include Wisp");
    const wispAction = before.legal_actions.find((action) => action.type === "PLAY_CARD" &&
      action.source_entity_id === wisp.entity_id && action.position === 0);
    assert(wispAction, "Wisp must have a legal insertion action at position 0");
    const wispCard = page.locator(`[data-testid="hand-card"][data-entity-id="${wisp.entity_id}"]`);
    const positionMarker = page.locator('.hand-drag-position-marker[data-position="0"]');
    const wispDrag = await dragFromHand(page, wispCard, async () => {
      await positionMarker.waitFor({ state: "visible", timeout });
      const markerBox = await positionMarker.boundingBox();
      assert(markerBox, "legal insertion marker must be visible");
      return { x: markerBox.x + markerBox.width / 2, y: markerBox.y + markerBox.height / 2 };
    }, pageErrors);
    assert(await positionMarker.evaluate((node) => node.classList.contains("hand-drag-hover")),
      "legal position must highlight under the pointer");
    await beginRevisionTrace(page);
    const wispSubmit = await sendFromUi(page, before, () => page.mouse.up(), "Wisp drag play");
    assert(sameAction(wispSubmit.action, wispAction), "valid drop must submit the exact legal Wisp action");
    const wispRevisions = await endRevisionTrace(page);
    assertDisplayedFrames(before, wispSubmit.payload, wispRevisions, "Wisp drag play");
    let state = await stateFromPage(page);
    assert(state.observation.self.board.some((card) => card.entity_id === wisp.entity_id),
      "dropped Wisp must appear on the battlefield");
    assert(await page.locator(".board-card").count() >= 1);

    const boar = state.observation.self.hand.find((card) => card.card_id === "CS2_171");
    assert(boar, "showcase hand must include Stonetusk Boar");
    const boarCard = page.locator(`[data-testid="hand-card"][data-entity-id="${boar.entity_id}"]`);
    const boarOriginBox = await boarCard.boundingBox();
    assert(boarOriginBox, "Stonetusk Boar must have a visible hand position");
    const originCenter = { x: boarOriginBox.x + boarOriginBox.width / 2, y: boarOriginBox.y + boarOriginBox.height / 2 };
    const requestCountBeforeInvalidDrop = actionRequests.length;
    await page.mouse.move(originCenter.x, originCenter.y);
    await page.mouse.down();
    await page.mouse.move(originCenter.x + 12, originCenter.y + 10, { steps: 3 });
    await page.locator(".hand-drag-ghost").waitFor({ state: "visible", timeout });
    await page.mouse.move(24, 24, { steps: 8 });
    const invalidSamplesPromise = page.evaluate(() => new Promise((resolve) => {
      const samples = [];
      const started = performance.now();
      const tick = () => {
        const ghost = document.querySelector(".hand-drag-ghost");
        if (ghost) {
          const rect = ghost.getBoundingClientRect();
          samples.push({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
        }
        if (performance.now() - started < 340) requestAnimationFrame(tick);
        else resolve(samples);
      };
      requestAnimationFrame(tick);
    }));
    await page.mouse.up();
    const invalidSamples = await invalidSamplesPromise;
    await page.locator(".hand-drag-ghost").waitFor({ state: "detached", timeout: 10000 });
    await page.waitForTimeout(250);
    assert(invalidSamples.length >= 4, `invalid drop should have a sampled return animation: ${JSON.stringify(invalidSamples)}`);
    const distances = invalidSamples.map((sample) => Math.hypot(sample.x - originCenter.x, sample.y - originCenter.y));
    assert(Math.max(...distances) > 45, "invalid-drop ghost should start away from its origin");
    assert(distances[distances.length - 1] < distances[0], "invalid-drop ghost should travel smoothly back toward its origin");
    assert.equal(actionRequests.length, requestCountBeforeInvalidDrop, "invalid drop must not submit an Action");
    assert(await boarCard.isVisible(), "invalidly dropped Boar must remain in hand");
    assert(!(await stateFromPage(page)).observation.self.board.some((card) => card.entity_id === boar.entity_id),
      "invalidly dropped Boar must not enter the battlefield");

    state = await stateFromPage(page);
    const fireball = state.observation.self.hand.find((card) => card.card_id === "CS2_029");
    assert(fireball, "showcase hand must include Fireball");
    const enemyHeroId = state.observation.opponent.hero.entity_id;
    const fireballAction = state.legal_actions.find((action) => action.type === "PLAY_CARD" &&
      action.source_entity_id === fireball.entity_id && action.target_entity_id === enemyHeroId);
    assert(fireballAction, "Fireball must have a legal opponent-hero target");
    const target = page.locator(`[data-testid="opponent-hero"] [data-entity-id="${enemyHeroId}"]`);
    const targetBox = await target.boundingBox();
    assert(targetBox, "opponent hero target must be visible");
    await beginRevisionTrace(page);
    await dragFromHand(page, page.locator(`[data-testid="hand-card"][data-entity-id="${fireball.entity_id}"]`),
      async () => {
        await target.waitFor({ state: "visible", timeout });
        const currentTargetBox = await target.boundingBox();
        assert(currentTargetBox, "opponent hero target should remain visible during drag");
        return { x: currentTargetBox.x + currentTargetBox.width / 2,
          y: currentTargetBox.y + currentTargetBox.height * .78 };
      }, pageErrors);
    assert(await target.evaluate((node) => node.classList.contains("hand-drag-target") &&
      node.classList.contains("hand-drag-hover")),
      "legal opponent hero target must highlight during the drag");
    const fireballResult = await sendFromUi(page, state, () => page.mouse.up(), "Fireball target drag");
    assert(sameAction(fireballResult.action, fireballAction), "target drop must submit the exact legal target action");
    const fireballRevisions = await endRevisionTrace(page);
    assertDisplayedFrames(state, fireballResult.payload, fireballRevisions, "Fireball target drag");

    const firstTurn = await captureEndTurn(page, await stateFromPage(page), "Human turn 1 end", consoleErrors);
    const firstOpponentEvents = firstTurn.payload.presentation_steps.map((frame) => frame.event)
      .filter((event) => event && event.actor === "opponent");
    const firstOpponentPlays = firstOpponentEvents.filter((event) => event.type === "PLAY_CARD");
    assert(firstOpponentPlays.length >= 2,
      `first AI turn should expose consecutive plays: ${JSON.stringify(firstOpponentEvents)}`);
    assert(firstOpponentEvents[0]?.type === "PLAY_CARD" && firstOpponentEvents[1]?.type === "PLAY_CARD",
      "AI card plays should be presented consecutively in action order");
    const firstAttackIndex = firstOpponentEvents.findIndex((event) => event.type === "ATTACK");
    let consecutiveAttacks = 0;
    for (let index = firstAttackIndex; index >= 0 && firstOpponentEvents[index]?.type === "ATTACK"; index += 1) {
      consecutiveAttacks += 1;
    }
    assert(consecutiveAttacks >= 2,
      `AI attacks should be presented consecutively: ${JSON.stringify(firstOpponentEvents)}`);
    assert(firstTurn.payload.presentation_steps.some((frame) => frame.event?.type === "END_TURN" &&
      frame.event.actor === "self"), "the human turn-switch action must have its own presentation frame");
    const playAnimations = await page.evaluate(() => window.__presentationAnimations.filter((item) =>
      item.className.includes("presentation-ghost") || item.className.includes("board-card")));
    assert(playAnimations.length >= 2, "AI plays should produce card or board WAAPI animation calls");

    const secondTurn = await captureEndTurn(page, await stateFromPage(page), "Human turn 2 end", consoleErrors);
    const secondOpponentEvents = secondTurn.payload.presentation_steps.map((frame) => frame.event)
      .filter((event) => event && event.actor === "opponent");
    const opponentAttacks = secondOpponentEvents.filter((event) => event.type === "ATTACK");
    assert(opponentAttacks.length >= 2,
      `second AI turn should expose consecutive attacks: ${JSON.stringify(secondOpponentEvents)}`);
    assert(secondOpponentEvents.filter((event) => event.type === "ATTACK").length === opponentAttacks.length);
    const attackAnimations = await page.evaluate(() => window.__presentationAnimations.filter((item) =>
      item.className.includes("board-card") || item.className.includes("presentation-number")));
    assert(attackAnimations.length > playAnimations.length,
      "AI attack and damage feedback should produce additional WAAPI animations");

    state = await stateFromPage(page);
    const boarNow = state.observation.self.hand.find((card) => card.card_id === "CS2_171");
    const enemyMinion = state.observation.opponent.board[0];
    assert(boarNow && enemyMinion, "AI actions must leave a target for a Charge minion trade");
    const boarPlay = state.legal_actions.find((action) => action.type === "PLAY_CARD" &&
      action.source_entity_id === boarNow.entity_id && action.position === 0);
    assert(boarPlay, "Stonetusk Boar must be playable at position 0");
    const boarMarker = page.locator('.hand-drag-position-marker[data-position="0"]');
    await dragFromHand(page, page.locator(`[data-testid="hand-card"][data-entity-id="${boarNow.entity_id}"]`), async () => {
      await boarMarker.waitFor({ state: "visible", timeout });
      const markerBox = await boarMarker.boundingBox();
      assert(markerBox, "Boar's legal insertion marker must be available");
      return { x: markerBox.x + markerBox.width / 2, y: markerBox.y + markerBox.height / 2 };
    }, pageErrors);
    const boarMarkerBox = await boarMarker.boundingBox();
    assert(boarMarkerBox, "Boar's legal insertion marker must remain available");
    const boarPlayResult = await sendFromUi(page, state, async () => {
      await page.mouse.move(boarMarkerBox.x + boarMarkerBox.width / 2,
        boarMarkerBox.y + boarMarkerBox.height / 2, { steps: 6 });
      await page.mouse.up();
    }, "Stonetusk Boar drag play");
    assert(sameAction(boarPlayResult.action, boarPlay), "Boar drop must submit its legal action");

    state = await stateFromPage(page);
    const boarOnBoard = state.observation.self.board.find((card) => card.entity_id === boarNow.entity_id);
    const liveEnemyMinion = state.observation.opponent.board[0];
    assert(boarOnBoard && liveEnemyMinion, "both combatants must be visible before the trade");
    const trade = state.legal_actions.find((action) => action.type === "ATTACK" &&
      action.source_entity_id === boarOnBoard.entity_id && action.target_entity_id === liveEnemyMinion.entity_id);
    assert(trade, "Charge Boar must have a legal attack against an AI Wisp");
    const animationCountBeforeTrade = await page.evaluate(() => window.__presentationAnimations.length);
    const tradeResult = await sendFromUi(page, state, async () => {
      await page.locator(`.sourceable[data-entity-id="${boarOnBoard.entity_id}"]`).click();
      await page.locator(`.targetable[data-entity-id="${liveEnemyMinion.entity_id}"]`).click();
    }, "Boar-Wisp trade");
    assert(sameAction(tradeResult.action, trade), "target selection must submit the exact legal attack");
    assert(!tradeResult.payload.observation.self.board.some((card) => card.entity_id === boarOnBoard.entity_id),
      "trading Stonetusk Boar must remove the dead attacker from the board");
    assert(!tradeResult.payload.observation.opponent.board.some((card) => card.entity_id === liveEnemyMinion.entity_id),
      "trading Stonetusk Boar must remove the dead Wisp from the board");
    const deathAnimations = await page.evaluate((count) => window.__presentationAnimations.slice(count)
      .filter((item) => item.effectType === "DEATH" || item.className.includes("presentation-ghost")), animationCountBeforeTrade);
    for (const id of [boarOnBoard.entity_id, liveEnemyMinion.entity_id]) {
      assert(deathAnimations.some(item => item.targetEntityId === id && item.effectType === "DEATH"),
        `dead entity ${id} must visibly animate before removal: ${JSON.stringify(deathAnimations)}`);
    }
    assert.equal(await page.locator(".presentation-ghost").count(), 0, "death ghosts should clean up after resolution");
    assert.deepEqual(pageErrors, [], `browser should not report page errors: ${pageErrors.join("\n")}`);

    console.log(JSON.stringify({
      result: "PASS",
      drag: {
        pointerFollowed: true,
        validAction: wispSubmit.action,
        invalidReturnSamples: invalidSamples.length,
        targetAction: fireballResult.action,
      },
      ai: {
        firstTurnEvents: firstOpponentEvents.map((event) => event.type),
        firstTurnRevisions: firstTurn.revisions,
        secondTurnEvents: secondOpponentEvents.map((event) => event.type),
        secondTurnRevisions: secondTurn.revisions,
      },
      deaths: deathAnimations.length,
      requests: actionRequests.length,
      artifacts,
    }, null, 2));
  } finally {
    if (context) await context.close();
    await stopFixture(fixture.child);
    if (browser) await browser.close();
  }
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
