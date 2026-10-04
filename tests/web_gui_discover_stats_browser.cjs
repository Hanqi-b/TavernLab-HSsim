#!/usr/bin/env node
/* Real-browser regression for live Discover and hand stats over stale card art. */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_discover_stats_browser_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || path.join(root, "venv/bin/python");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-web-gui-discover-stats-artifacts");
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);

function startFixture(locale) {
  const child = spawn(python, ["-u", fixture, "--port", "0", "--locale", locale], {
    cwd: root,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`fixture startup timed out\n${logs.join("")}`)), timeout);
    readline.createInterface({ input: child.stdout }).on("line", (line) => {
      logs.push(`${line}\n`);
      try {
        const value = JSON.parse(line);
        if (value && typeof value.url === "string" && value.locale === locale) {
          clearTimeout(timer);
          resolve(value);
        }
      } catch (_error) { /* card database startup logs can precede the ready JSON */ }
    });
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      reject(new Error(`fixture exited before ready (code=${code}, signal=${signal})\n${logs.join("")}`));
    });
  });
  return { child, ready, logs };
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

async function stateFromPage(page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`GET /api/state failed: ${response.status}`);
    return response.json();
  });
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

async function waitForState(page, predicate, description) {
  const deadline = Date.now() + timeout;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await stateFromPage(page);
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`timed out waiting for ${description}: ${JSON.stringify(latest)}`);
}

async function submitByUi(page, before, click, expectedType) {
  const requestPromise = page.waitForRequest((request) =>
    request.method() === "POST" && new URL(request.url()).pathname === "/api/action", { timeout });
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/action", { timeout });
  await click();
  const request = await requestPromise;
  const body = request.postDataJSON();
  assert.equal(body.revision, before.revision, "GUI should submit its current revision");
  assert.equal(body.session_id, before.session_id, "GUI should submit its current session");
  assert.equal(body.action.type, expectedType, `expected ${expectedType}: ${JSON.stringify(body.action)}`);
  assert(before.legal_actions.some((action) => JSON.stringify(canonical(action)) === JSON.stringify(canonical(body.action))),
    `GUI submitted an action absent from the legal action snapshot: ${JSON.stringify(body.action)}`);
  const response = await responsePromise;
  const payload = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(payload));
  await page.waitForFunction(() => window.fireplaceWebGui && !window.fireplaceWebGui.isBusy(), null, { timeout });
  return { action: body.action, payload };
}

async function modalStats(page) {
  return page.locator("#modal-stats .stat").evaluateAll((stats) => Object.fromEntries(
    stats.map((stat) => [
      [...stat.classList].find((name) => ["cost", "attack", "health", "durability"].includes(name)),
      { value: stat.querySelector("strong")?.textContent.trim(), label: stat.querySelectorAll("span")[0]?.textContent.trim() },
    ]),
  ));
}

async function liveOverlay(page, selector) {
  return page.locator(`${selector} .card-live-stats`).evaluate((overlay) => {
    const art = overlay.parentElement;
    const image = art.querySelector("img");
    const names = ["cost", "attack", "health"];
    const values = {};
    for (const name of names) {
      const node = overlay.querySelector(`.card-live-stat-${name}`);
      if (node) values[name] = {
        value: node.textContent.trim(),
        classes: [...node.classList],
        borderColor: getComputedStyle(node).borderTopColor,
        rect: (() => { const rect = node.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }; })(),
      };
    }
    const rect = overlay.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    return {
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      overlay: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      imageBox: { x: imageRect.x, y: imageRect.y, width: imageRect.width, height: imageRect.height },
      values,
    };
  });
}

function assertLiveStats(overlay, expected, label) {
  assert(overlay.naturalWidth > 0 && overlay.naturalHeight > 0, `${label}: the controlled stale render should load`);
  assert.deepEqual({
    cost: overlay.values.cost?.value,
    attack: overlay.values.attack?.value,
    health: overlay.values.health?.value,
  }, expected, `${label}: overlay values must follow the live observation`);
  const health = overlay.values.health;
  const relativeWidth = health.rect.width / overlay.overlay.width;
  assert(relativeWidth >= 0.24 && relativeWidth <= 0.28,
    `${label}: health marker should scale with rendered image width (${relativeWidth})`);
  assert(health.rect.x + health.rect.width <= overlay.overlay.x + overlay.overlay.width + 1,
    `${label}: health marker should stay over the rendered image`);
}

async function runLocale(browser, locale) {
  const server = startFixture(locale);
  let context;
  try {
    const fixtureInfo = await server.ready;
    const base = fixtureInfo.url;
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const pageErrors = [];
    const remoteRequests = [];
    const renderResponses = [];
    page.on("pageerror", (error) => pageErrors.push(error.stack || String(error)));
    page.on("request", (request) => {
      if (new URL(request.url()).origin !== new URL(base).origin) remoteRequests.push(request.url());
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.pathname === "/assets/render/LOOT_137") {
        renderResponses.push({ status: response.status(), headers: response.headers() });
      }
    });
    // The front end always requires an authenticated-session handshake. This
    // isolated WebGame fixture has no account backend or account database.
    await page.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ authenticated: true, account: { id: "fixture-only", username: "Fixture" }, legacy_available: false }),
    }));

    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.locator("#game").waitFor({ state: "visible", timeout });
    let state = await waitForState(page, (value) => value.observation?.phase === "MULLIGAN", "opening mulligan");
    assert.equal(state.locale, locale);
    assert.equal(state.observation.self.hand.length, 3);
    await submitByUi(page, state, () => page.locator("#action-submit").click(), "MULLIGAN");

    state = await waitForState(page, (value) => value.observation?.phase === "MAIN" &&
      value.observation.self.hand.some((card) => card.card_id === "KAR_062"), "fixture hand after mulligan");
    const historian = state.observation.self.hand.find((card) => card.card_id === "KAR_062");
    const startingSleepy = state.observation.self.hand.find((card) => card.card_id === "LOOT_137");
    assert(historian && startingSleepy, "fixture should expose the Discover source and a Dragon condition card");
    assert.equal(startingSleepy.atk, 4);
    assert.equal(startingSleepy.max_health, 12);

    const historianCard = page.locator(`[data-testid="hand-card"][data-entity-id="${historian.entity_id}"]`);
    await historianCard.click();
    const position = page.locator('#position-choices button[data-position="0"]');
    await position.waitFor({ state: "visible", timeout });
    const playResult = await submitByUi(page, state, () => position.click(), "PLAY_CARD");
    assert.equal(playResult.action.source_entity_id, historian.entity_id);
    assert.equal(playResult.action.position, 0);

    state = await waitForState(page, (value) => value.observation?.phase === "CHOICE" &&
      value.observation.pending_choice?.options?.some((card) => card.card_id === "LOOT_137"), "Sleepy Dragon Discover");
    const sleepyOption = state.observation.pending_choice.options.find((card) => card.card_id === "LOOT_137");
    assert.deepEqual({
      cost: sleepyOption.cost,
      printed_cost: sleepyOption.printed_cost,
      atk: sleepyOption.atk,
      printed_atk: sleepyOption.printed_atk,
      max_health: sleepyOption.max_health,
      printed_health: sleepyOption.printed_health,
    }, { cost: 9, printed_cost: 9, atk: 4, printed_atk: 4, max_health: 12, printed_health: 12 });
    assert.equal(state.observation.opponent.pending_choice, undefined,
      "the opponent projection must not gain a pending choice field");
    assert.equal("hand" in state.observation.opponent, false);
    assert(!JSON.stringify(state.observation.opponent).includes("LOOT_137"));

    const option = page.locator(`.option-card[data-entity-id="${sleepyOption.entity_id}"]`);
    await option.waitFor({ state: "visible", timeout });
    await page.waitForFunction((selector) => {
      const image = document.querySelector(`${selector} .card-art img`);
      return image && image.naturalWidth > 0 && image.naturalHeight > 0;
    }, `.option-card[data-entity-id="${sleepyOption.entity_id}"]`, { timeout });
    const optionOverlay = await liveOverlay(page, `.option-card[data-entity-id="${sleepyOption.entity_id}"]`);
    assertLiveStats(optionOverlay, { cost: "9", attack: "4", health: "12" }, `${locale} choice`);

    await option.locator('[data-testid="card-inspect"]').click();
    await page.locator("#card-modal").waitFor({ state: "visible", timeout });
    assert.equal(await page.locator("#modal-card-id").innerText(), "LOOT_137");
    assert.deepEqual(await modalStats(page), {
      cost: { value: "9", label: locale === "enUS" ? "Cost" : "费用" },
      attack: { value: "4", label: locale === "enUS" ? "Attack" : "攻击" },
      health: { value: "12", label: locale === "enUS" ? "Health" : "生命" },
    });
    const preModalOverlay = await liveOverlay(page, "#modal-art");
    assertLiveStats(preModalOverlay, { cost: "9", attack: "4", health: "12" }, `${locale} pre-buff modal`);
    await page.screenshot({ path: path.join(artifacts, `discover-stats-${locale}-choice-modal.png`), fullPage: true });
    await page.locator("#modal-close").click();
    await page.locator("#card-modal").waitFor({ state: "hidden", timeout });

    const chooseResult = await submitByUi(page, state,
      () => option.click({ force: true }), "CHOOSE");
    assert.equal(chooseResult.action.choice_entity_id, sleepyOption.entity_id);
    state = await waitForState(page, (value) => value.observation?.phase === "MAIN" &&
      value.observation.self.hand.some((card) => card.entity_id === sleepyOption.entity_id && card.atk === 5 && card.max_health === 14),
    "engine +1/+2 display-fixture enchantment in hand");
    const handSleepy = state.observation.self.hand.find((card) => card.entity_id === sleepyOption.entity_id);
    assert.deepEqual({ atk: handSleepy.atk, max_health: handSleepy.max_health,
      printed_atk: handSleepy.printed_atk, printed_health: handSleepy.printed_health },
    { atk: 5, max_health: 14, printed_atk: 4, printed_health: 12 });
    assert(handSleepy.active_modifiers.some((modifier) => modifier.effect?.card_id === "DRG_233e"),
      "hand snapshot should retain the actual engine enchantment");

    const handSelector = `[data-testid="hand-card"][data-entity-id="${handSleepy.entity_id}"]`;
    await page.locator(handSelector).hover();
    const handOverlay = await liveOverlay(page, handSelector);
    assertLiveStats(handOverlay, { cost: "9", attack: "5", health: "14" }, `${locale} hovered hand`);
    assert(handOverlay.values.attack.classes.includes("stat-higher"));
    assert(handOverlay.values.health.classes.includes("stat-higher"));
    await page.screenshot({ path: path.join(artifacts, `discover-stats-${locale}-hand-hover.png`), fullPage: true });

    await page.locator(`${handSelector} [data-testid="card-inspect"]`).click();
    await page.locator("#card-modal").waitFor({ state: "visible", timeout });
    assert.deepEqual(await modalStats(page), {
      cost: { value: "9", label: locale === "enUS" ? "Cost" : "费用" },
      attack: { value: "5", label: locale === "enUS" ? "Attack" : "攻击" },
      health: { value: "14", label: locale === "enUS" ? "Health" : "生命" },
    });
    let postModalOverlay = await liveOverlay(page, "#modal-art");
    assertLiveStats(postModalOverlay, { cost: "9", attack: "5", health: "14" }, `${locale} post-buff modal`);
    assert(postModalOverlay.values.health.classes.includes("stat-higher"));
    assert(postModalOverlay.values.health.borderColor.includes("139, 229, 154"),
      `${locale}: increased health should receive the green live-stat marker`);
    await page.screenshot({ path: path.join(artifacts, `discover-stats-${locale}-hand-modal-desktop.png`), fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(100);
    const mobileBounds = await page.locator("#card-modal .card-modal-dialog").boundingBox();
    assert(mobileBounds && mobileBounds.x >= 0 && mobileBounds.x + mobileBounds.width <= 390,
      `${locale}: mobile card modal must fit the viewport: ${JSON.stringify(mobileBounds)}`);
    const mobileScrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    assert(mobileScrollWidth <= 390, `${locale}: mobile view has horizontal overflow (${mobileScrollWidth}px)`);
    postModalOverlay = await liveOverlay(page, "#modal-art");
    assertLiveStats(postModalOverlay, { cost: "9", attack: "5", health: "14" }, `${locale} resized mobile modal`);
    await page.screenshot({ path: path.join(artifacts, `discover-stats-${locale}-hand-modal-mobile.png`), fullPage: true });

    const successfulRender = renderResponses.find((response) => response.status === 200 &&
      response.headers["x-asset-placeholder"] === "0");
    assert(successfulRender, `${locale}: no controlled LOOT_137 render response: ${JSON.stringify(renderResponses)}`);
    assert(successfulRender.headers["content-type"].startsWith("image/"));
    assert.equal(remoteRequests.length, 0, `fixture must not make external requests: ${remoteRequests.join(", ")}`);
    assert.equal(pageErrors.length, 0, pageErrors.join("\n"));
    console.log(JSON.stringify({
      locale,
      result: "PASS",
      renderOrigin: fixtureInfo.render_origin,
      renderMediaType: fixtureInfo.render_media_type,
      renderNaturalSize: [postModalOverlay.naturalWidth, postModalOverlay.naturalHeight],
      desktopHealthMarkerWidth: Math.round(postModalOverlay.values.health.rect.width * 10) / 10,
      mobileHealthMarkerWidth: Math.round(postModalOverlay.values.health.rect.width * 10) / 10,
      screenshots: [
        `discover-stats-${locale}-choice-modal.png`,
        `discover-stats-${locale}-hand-hover.png`,
        `discover-stats-${locale}-hand-modal-desktop.png`,
        `discover-stats-${locale}-hand-modal-mobile.png`,
      ].map((name) => path.join(artifacts, name)),
    }));
  } finally {
    if (context) await context.close();
    await stopFixture(server.child);
  }
}

async function main() {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({
    headless: process.env.FIREPLACE_GUI_HEADFUL !== "1",
    executablePath: chrome,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    await runLocale(browser, "zhCN");
    await runLocale(browser, "enUS");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
