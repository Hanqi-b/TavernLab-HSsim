#!/usr/bin/env node
/* Browser acceptance check for localized, responsive deck-count badges. */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_locale_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || path.join(root, "venv/bin/python");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-web-gui-deck-count-artifacts");
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);

function startFixture() {
  const child = spawn(python, ["-u", fixture, "--port", "0"], {
    cwd: root,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`fixture startup timed out\n${logs.join("")}`)), 30000);
    readline.createInterface({ input: child.stdout }).on("line", (line) => {
      logs.push(`${line}\n`);
      try {
        const value = JSON.parse(line);
        if (value && typeof value.url === "string") {
          clearTimeout(timer);
          resolve(value);
        }
      } catch (_error) {
        // Engine diagnostics can precede the fixture's readiness JSON.
      }
    });
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      reject(new Error(`fixture exited before ready (code=${code}, signal=${signal})\n${logs.join("")}`));
    });
  });
  return { child, ready };
}

async function stopFixture(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

function localizedCount(locale, side, value) {
  const label = side === "self"
    ? (locale === "enUS" ? "Your deck count" : "你的牌库数量")
    : (locale === "enUS" ? "Opponent deck count" : "对手牌库数量");
  const text = locale === "enUS" ? `Deck ${value}` : `牌库 ${value}`;
  return { text, aria: locale === "enUS" ? `${label}: ${value}` : `${label}：${value}` };
}

function decorateSnapshot(payload, counts) {
  if (!payload.observation || !payload.observation.self || !payload.observation.opponent) return;
  payload.observation.self.deck_count = counts.self;
  payload.observation.opponent.deck_count = counts.opponent;
  payload.observation.phase = "MAIN";
  payload.observation.turn = counts.turn || 1;
  payload.observation.active_seat = 0;
  payload.observation.self.mana = 10;
  payload.observation.self.max_mana = 10;
  payload.observation.self.board = Array.from({ length: 7 }, (_, index) => ({
    entity_id: 9910 + index,
    card_id: "CS2_231",
    name: "Board Test",
    atk: 1,
    health: 1,
    max_health: 1,
  }));
  // Keep the mobile geometry check honest: these public status lanes share
  // the same lower board space as the own resources badge.
  payload.observation.self.secrets = [{ entity_id: 9901, card_id: "EX1_611", name: "Test Secret" }];
  payload.observation.self.quests = [{ entity_id: 9902, card_id: "UNG_940", name: "Test Quest", progress: 1, progress_total: 2 }];
  payload.observation.opponent.secrets_count = 1;
  payload.observation.opponent.secret_classes = [["MAGE"]];
  payload.observation.opponent.quests = [{ entity_id: 9903, card_id: "UNG_940", name: "Opponent Quest", progress: 1, progress_total: 2 }];
}

async function assertCounts(page, locale, counts) {
  for (const [side, id] of [["self", "#deck-count"], ["opponent", "#opponent-deck-count"]]) {
    const expected = localizedCount(locale, side, counts[side]);
    const node = page.locator(id);
    assert.equal(await node.count(), 1, `${id} must be unique`);
    assert.equal(await node.innerText(), expected.text, `${id} should render the localized count`);
    assert.equal(await node.getAttribute("aria-label"), expected.aria, `${id} should expose the current count`);
    assert(await node.isVisible(), `${id} should remain visible`);
  }
}

function overlaps(left, right) {
  return left && right && left.x < right.x + right.width && left.x + left.width > right.x &&
    left.y < right.y + right.height && left.y + left.height > right.y;
}

async function assertGeometry(page, viewportName) {
  const result = await page.evaluate(() => {
    const ids = ["deck-count", "opponent-deck-count"];
    const boxes = Object.fromEntries(ids.map((id) => {
      const node = document.getElementById(id);
      const box = node?.getBoundingClientRect();
      return [id, box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null];
    }));
    const otherNodes = [
      ["hand", document.getElementById("hand")],
      ["opponent-hand", document.getElementById("opponent-hand")],
      ["self-hero-row", document.getElementById("self-hero-row")],
      ["opponent-hero-row", document.getElementById("opponent-hero-row")],
      ["mana-value", document.getElementById("mana-value")],
      ["phase-value", document.getElementById("phase-value")],
      ["turn-value", document.getElementById("turn-value")],
      ["end-turn-button", document.getElementById("end-turn-button")],
    ];
    document.querySelectorAll(".hero-status-card, #self-board .stat, #opponent-board .stat").forEach((node, index) => {
      otherNodes.push([`visible-card-detail-${index}`, node]);
    });
    const otherBoxes = Object.fromEntries(otherNodes.map(([id, node]) => {
      const box = node?.getBoundingClientRect();
      return [id, box && box.width > 0 && box.height > 0 ? {
        x: box.x, y: box.y, width: box.width, height: box.height,
      } : null];
    }));
    const stack = Object.fromEntries(ids.map((id) => {
      const box = boxes[id];
      if (!box) return [id, []];
      const node = document.getElementById(id);
      const previousPointerEvents = node.style.pointerEvents;
      // The own badge is intentionally click-through; temporarily opt it into
      // hit testing so this check still catches visual obstruction.
      node.style.pointerEvents = "auto";
      const stack = document.elementsFromPoint(box.x + box.width / 2, box.y + box.height / 2)
        .map((node) => node.id || node.className || node.tagName);
      node.style.pointerEvents = previousPointerEvents;
      return [id, stack];
    }));
    return {
      boxes,
      otherBoxes,
      stack,
      selfPointerEvents: getComputedStyle(document.getElementById("deck-count")).pointerEvents,
    };
  });
  for (const id of ["deck-count", "opponent-deck-count"]) {
    const box = result.boxes[id];
    assert(box && box.width > 0 && box.height > 0, `${id} must have a rendered box at ${viewportName}`);
    assert.equal(result.stack[id][0], id, `${id} must be the topmost element in its browser hit-test stack at ${viewportName}`);
    for (const [otherId, otherBox] of Object.entries(result.otherBoxes)) {
      assert(!overlaps(box, otherBox), `${id} must not overlap ${otherId} at ${viewportName}: ${JSON.stringify({ box, otherBox })}`);
    }
  }
  assert.equal(result.selfPointerEvents, "none", "own count badge must remain informational");
}

async function runLocale(browser, locale) {
  const server = startFixture();
  const counts = { self: 12, opponent: 8 };
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  let page;
  const diagnostics = [];
  const apiTrace = [];
  try {
    const fixtureInfo = await server.ready;
    await context.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, account: { id: "deck-count-fixture", username: "Deck Count Tester" }, legacy_available: false }),
    }));
    await context.route("**/api/decks*", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ decks: [] }),
    }));
    await context.route("**/api/state", async (route) => {
      const response = await route.fetch();
      const body = await response.body();
      const payload = JSON.parse(body.toString("utf8"));
      apiTrace.push({ path: "/api/state", status: response.status(), mode: payload.mode || "match" });
      decorateSnapshot(payload, counts);
      await route.fulfill({ response, body: JSON.stringify(payload) });
    });
    await context.route("**/api/start", async (route) => {
      const response = await route.fetch();
      const body = await response.body();
      const payload = JSON.parse(body.toString("utf8"));
      apiTrace.push({ path: "/api/start", status: response.status(), mode: payload.mode || "match" });
      decorateSnapshot(payload, counts);
      await route.fulfill({ response, body: JSON.stringify(payload) });
    });
    page = await context.newPage();
    page.setDefaultTimeout(timeout);
    page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error}`));
    page.on("console", (message) => {
      // The local resolver intentionally lacks art for the mocked status cards.
      if (message.type() === "error" && !message.text().includes("404 (Not Found)")) {
        diagnostics.push(`console: ${message.text()}`);
      }
    });
    await page.goto(fixtureInfo.url, { waitUntil: "domcontentloaded" });
    await page.locator("#lobby-screen").waitFor({ state: "visible", timeout });
    await page.locator(`#locale-${locale}`).click();
    await page.locator("#nickname-input").fill("Deck Count Tester");
    if (await page.locator("#enter-lobby-button").isVisible()) await page.locator("#enter-lobby-button").click();
    await page.locator("#lobby-setup").waitFor({ state: "visible" });
    await page.locator("#start-match-button").click();
    await page.locator("#game").waitFor({ state: "visible" });
    await page.locator("#deck-count").waitFor({ state: "visible" });
    await assertCounts(page, locale, counts);
    await assertGeometry(page, "desktop");
    await page.screenshot({ path: path.join(artifacts, `deck-counts-${locale}-desktop.png`), fullPage: true });

    counts.self = 11;
    counts.opponent = 7;
    await page.evaluate(() => window.fireplaceWebGui.loadState(true));
    await page.waitForFunction((expected) => document.querySelector("#deck-count")?.textContent.trim() === expected,
      localizedCount(locale, "self", counts.self).text);
    await assertCounts(page, locale, counts);

    counts.self = 0;
    counts.opponent = 0;
    await page.evaluate(() => window.fireplaceWebGui.loadState(true));
    await page.waitForFunction(() => document.querySelector("#deck-count")?.textContent.trim().endsWith("0"));
    await assertCounts(page, locale, counts);

    counts.self = 30;
    counts.opponent = 30;
    for (const width of [320, 390, 700]) {
      await page.setViewportSize({ width, height: 844 });
      for (const turn of [1, 120]) {
        counts.turn = turn;
        await page.evaluate(() => window.fireplaceWebGui.loadState(true));
        await page.waitForFunction((expected) => document.querySelector("#deck-count")?.textContent.trim() === expected,
          localizedCount(locale, "self", counts.self).text);
        await assertCounts(page, locale, counts);
        await assertGeometry(page, `mobile-${width}-turn-${turn}`);
      }
      await page.screenshot({ path: path.join(artifacts, `deck-counts-${locale}-${width}.png`), fullPage: true });
    }
    assert.deepEqual(diagnostics, [], `browser diagnostics for ${locale}; API trace=${JSON.stringify(apiTrace)}`);
    return { locale, result: "PASS" };
  } finally {
    await context.close();
    await stopFixture(server.child);
  }
}

(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: chrome, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
  try {
    for (const locale of ["zhCN", "enUS"]) console.log(JSON.stringify(await runLocale(browser, locale)));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
