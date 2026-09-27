#!/usr/bin/env node
/*
 * Browser acceptance test for the standalone arena flow.
 *
 * This test uses a tiny in-process API fixture so it can exercise the page
 * without requiring a configured card pool or a running match server.
 */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const webRoot = path.join(root, "fireplace", "web_gui");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";

function fixtureCard(index) {
  return {
    id: `AT_${String(index + 1).padStart(3, "0")}`,
    name: `Draft card ${index + 1}`,
    text: index % 2 ? "A blank card for the first arena pass." : "A test card with an effect.",
    cost: index % 8 === 7 ? 9 : index % 8,
    attack: index % 5,
    health: 2 + (index % 6),
    card_set: index % 2 ? "TGT" : "BASIC",
    class: index % 3 ? "NEUTRAL" : "MAGE",
    has_python_script: index % 2 === 0,
  };
}

function initialState() {
  return {
    mode: "setup",
    revision: 0,
    nickname: "",
    locale: "zhCN",
    wins: 0,
    losses: 0,
    selected_sets: [],
    pack_options: {
      basic: { id: "BASIC", label: "Basic", count: 120 },
      classic: { id: "EXPERT1", label: "Classic", count: 240 },
      large: [
        { id: "LARGE_A", label: "Large A", count: 120 },
        { id: "LARGE_B", label: "Large B", count: 110 },
        { id: "LARGE_C", label: "Large C", count: 105 },
        { id: "LARGE_D", label: "Large D", count: 130 },
        { id: "LARGE_E", label: "Large E", count: 101 },
      ],
      small: [{ id: "SMALL_A", label: "Small A", count: 40 }],
    },
    hero_offer: [],
    card_offer: [],
    deck: [],
  };
}

function heroes() {
  return [
    { id: "HERO_01", name: "Mage", class: "MAGE", card_set: "BASIC", text: "A basic hero." },
    { id: "HERO_02", name: "Hunter", class: "HUNTER", card_set: "BASIC", text: "A basic hero." },
    { id: "HERO_03", name: "Priest", class: "PRIEST", card_set: "BASIC", text: "A basic hero." },
  ];
}

function json(response, status, body) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
  });
  response.end(payload);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let value = "";
    request.on("data", (chunk) => { value += chunk; });
    request.on("end", () => {
      try { resolve(value ? JSON.parse(value) : {}); } catch (error) { reject(error); }
    });
    request.on("error", reject);
  });
}

function startFixture() {
  const state = initialState();
  let artRequests = 0;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/api/account/session" && request.method === "GET") {
      return json(response, 200, {
        authenticated: true,
        account: { id: "fixture-account", username: "Arena Fixture" },
        legacy_available: false,
      });
    }
    if (url.pathname === "/api/arena/state") return json(response, 200, state);
    if (url.pathname.startsWith("/catalog/assets/art/")) {
      const body = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="388"><rect width="256" height="388" fill="#315b7d"/><text x="128" y="200" text-anchor="middle" fill="#fff" font-size="18">CARD</text></svg>`;
      artRequests += 1;
      if (artRequests <= 2) {
        response.writeHead(202, { "Content-Length": "0" });
        response.end();
        return;
      }
      response.writeHead(200, { "Content-Type": "image/svg+xml", "Content-Length": Buffer.byteLength(body) });
      response.end(body);
      return;
    }
    if (url.pathname === "/api/arena/start" && request.method === "POST") {
      const body = await readBody(request);
      state.mode = "hero";
      state.revision += 1;
      state.run_id = "fixture-run";
      state.nickname = body.nickname;
      state.locale = body.locale;
      state.selected_sets = body.set_ids || [];
      state.hero_offer = heroes();
      return json(response, 200, state);
    }
    if (url.pathname === "/api/arena/hero" && request.method === "POST") {
      const body = await readBody(request);
      state.mode = "draft";
      state.revision += 1;
      state.hero = heroes().find((hero) => hero.id === body.hero_id) || heroes()[0];
      state.card_offer = [fixtureCard(state.deck.length), fixtureCard(state.deck.length + 1), fixtureCard(state.deck.length + 2)];
      return json(response, 200, state);
    }
    if (url.pathname === "/api/arena/pick" && request.method === "POST") {
      const body = await readBody(request);
      const offered = state.card_offer.find((card) => card.id === body.card_id) || state.card_offer[0];
      state.deck.push(offered);
      state.revision += 1;
      if (state.deck.length === 30) {
        state.mode = "ready";
        state.card_offer = [];
      } else {
        state.card_offer = [fixtureCard(state.deck.length), fixtureCard(state.deck.length + 1), fixtureCard(state.deck.length + 2)];
      }
      return json(response, 200, state);
    }
    if (url.pathname === "/api/arena/battle" && request.method === "POST") {
      await readBody(request);
      state.mode = "match";
      state.revision += 1;
      return json(response, 200, state);
    }
    if (url.pathname === "/api/arena/reset" && request.method === "POST") {
      await readBody(request);
      Object.assign(state, initialState());
      return json(response, 200, state);
    }
    if ((url.pathname === "/" || url.pathname === "/arena.html") && url.searchParams.get("arena") === "1") {
      const body = "<!doctype html><title>Match</title><main data-testid=arena-match-page>match page</main>";
      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      response.end(body);
      return;
    }
    const relative = url.pathname === "/" ? "arena.html" : url.pathname.replace(/^\//, "");
    const file = path.resolve(webRoot, relative);
    if (!file.startsWith(`${webRoot}${path.sep}`) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404);
      response.end("not found");
      return;
    }
    const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".webp": "image/webp" };
    response.writeHead(200, { "Content-Type": `${types[path.extname(file)] || "application/octet-stream"}; charset=utf-8` });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    resolve({ server, base: `http://127.0.0.1:${port}/`, get artRequests() { return artRequests; } });
  }));
}

async function main() {
  const fixture = await startFixture();
  const browser = await chromium.launch({ executablePath: chrome, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  const artifactDir = "/tmp/fireplace-web-gui-artifacts";
  fs.mkdirSync(artifactDir, { recursive: true });
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(fixture.base);
    await page.locator('[data-testid="arena-stage"]').waitFor({ state: "visible" });
    await page.screenshot({ path: path.join(artifactDir, "arena-setup-desktop.png"), fullPage: true });
    assert.equal(await page.locator('[data-testid="arena-basic-lock"]').count(), 1);
    assert.equal(await page.locator('[data-testid="arena-classic-lock"]').count(), 1);
    assert.equal(await page.locator('[data-pack-id="EXPERT1"]').count(), 0);
    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, "setup must fit a narrow viewport");
    await page.screenshot({ path: path.join(artifactDir, "arena-setup-mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator('[data-testid="arena-nickname"]').fill("Arena tester");
    assert.equal(await page.locator('[data-testid="arena-start"]').isDisabled(), true);

    const large = page.locator('[data-action="toggle-pack"][data-pack-size="large"]');
    const small = page.locator('[data-action="toggle-pack"][data-pack-size="small"]');
    for (let index = 0; index < 5; index += 1) await large.nth(index).click();
    await small.first().click();
    assert.equal(await page.locator('[data-testid="arena-start"]').isDisabled(), false);
    assert.match(await page.locator(".arena-budget-ring").textContent(), /16/);
    await page.locator('[data-testid="arena-start"]').click();

    await page.locator('[data-testid="arena-hero-offer"]').waitFor();
    assert.equal(await page.locator('[data-testid="arena-hero-offer"] [data-action="choose-hero"]').count(), 3);
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="arena-hero-offer"] img[data-arena-image]')].every((image) => image.dataset.imageState === "loaded"));
    await page.waitForFunction(() => !document.getElementById("arena-status").textContent.trim());
    await page.screenshot({ path: path.join(artifactDir, "arena-hero-desktop.png"), fullPage: true });
    assert(fixture.artRequests >= 3, "arena art loader must retry a temporary 202 response");
    await page.locator('[data-action="choose-hero"]').first().click();
    await page.locator('[data-testid="arena-card-offer"]').waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="arena-card-offer"] img[data-arena-image]')].every((image) => image.dataset.imageState === "loaded"));
    await page.waitForFunction(() => !document.getElementById("arena-status").textContent.trim());
    assert.equal(await page.locator('[data-testid="arena-mana-curve"] .arena-mana-column').count(), 8);
    await page.screenshot({ path: path.join(artifactDir, "arena-draft-desktop.png"), fullPage: true });

    for (let count = 1; count <= 30; count += 1) {
      await page.locator('[data-testid="arena-card-offer"] [data-action="pick-card"]').first().click();
      await page.waitForFunction((expected) => document.querySelectorAll("[data-testid=arena-deck] .arena-deck-row").length === expected, count);
      const costs = await page.locator('[data-testid="arena-deck"] [data-card-cost]').evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.cardCost)));
      assert.deepEqual(costs, [...costs].sort((a, b) => a - b), `deck must be sorted after pick ${count}`);
      const curveCounts = await page.locator('[data-testid="arena-mana-curve"] .arena-mana-column').evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.count)));
      assert.equal(curveCounts.reduce((total, value) => total + value, 0), count, `curve must update after pick ${count}`);
      if (count === 10) {
        assert.deepEqual(curveCounts, [2, 2, 1, 1, 1, 1, 1, 1]);
        await page.screenshot({ path: path.join(artifactDir, "arena-draft-curve.png"), fullPage: true });
        await page.setViewportSize({ width: 375, height: 812 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, "draft curve must fit a narrow viewport");
        await page.screenshot({ path: path.join(artifactDir, "arena-draft-curve-mobile.png"), fullPage: true });
        await page.setViewportSize({ width: 1440, height: 900 });
      }
    }
    assert.equal(await page.locator('[data-testid="arena-battle"]').count(), 1);
    assert.equal(await page.locator('[data-testid="arena-deck"] .arena-deck-row').count(), 30);
    assert.deepEqual(await page.locator('[data-testid="arena-mana-curve"] .arena-mana-column').evaluateAll((nodes) => nodes.map((node) => Number(node.dataset.count))), [4, 4, 4, 4, 4, 4, 3, 3]);
    await page.screenshot({ path: path.join(artifactDir, "arena-ready-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, "ready curve must fit a narrow viewport");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator('[data-testid="arena-battle"]').click();
    await page.locator('[data-testid="arena-match-page"]').waitFor();
    assert.match(page.url(), /[?&]arena=1/);

    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log("arena browser acceptance passed");
  } finally {
    await browser.close();
    fixture.server.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
