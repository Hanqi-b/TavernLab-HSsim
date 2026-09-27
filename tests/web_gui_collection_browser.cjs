#!/usr/bin/env node
/* Browser acceptance test for the standalone collection/deck builder. */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const webRoot = path.join(root, "fireplace", "web_gui");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(require("node:os").tmpdir(), "fireplace-web-gui-artifacts");

function card(index, cardClass = "MAGE", overrides = {}) {
  return {
    id: `COL_${String(index).padStart(3, "0")}`,
    name: `${cardClass === "NEUTRAL" ? "Neutral" : "Mage"} card ${index}`,
    text: "A small fixture card.",
    cost: index % 8,
    attack: index % 5 + 1,
    health: index % 6 + 1,
    card_set: index % 2 ? "EXPERT1" : "GVG",
    catalog_set: index % 2 ? "EXPERT1" : "GVG",
    class: cardClass,
    classes: [cardClass],
    type: "MINION",
    rarity: "COMMON",
    collectible: true,
    ...overrides,
  };
}

function hero(id, name, cardClass) {
  return { id, name, class: cardClass, classes: [cardClass], card_set: "BASIC", type: "HERO", cost: 0 };
}

function initialState() {
  return {
    decks: [],
    heroes: [hero("HERO_01", "Mage", "MAGE"), hero("HERO_02", "Hunter", "HUNTER")],
    locale: "zhCN",
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function json(response, status, body) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
  });
  response.end(payload);
}

function renderedFace(cardId) {
  const hue = cardId.endsWith("1") ? "#a94442" : "#365f86";
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120" viewBox="0 0 80 120"><rect x="1" y="1" width="78" height="118" rx="7" fill="#171b2b" stroke="#e3c079" stroke-width="2"/><path d="M8 9h64v18H8z" fill="${hue}"/><circle cx="40" cy="59" r="23" fill="${hue}" stroke="#f5dca0" stroke-width="2"/><path d="M8 91h64v19H8z" fill="#75613f"/><text x="40" y="22" fill="white" font-size="8" text-anchor="middle">${cardId}</text></svg>`);
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
  const cards = [
    ...Array.from({ length: 14 }, (_value, index) => card(index + 1, "MAGE")),
    card(15, "MAGE"),
    card(16, "MAGE", { id: "COL_016", name: "Spell fallback fixture", type: "SPELL", attack: undefined, health: undefined }),
    card(17, "MAGE", { id: "COL_017", name: "Weapon fallback fixture", type: "WEAPON", attack: 3, durability: 2, health: undefined }),
    card(18, "MAGE", { id: "COL_018", name: "Placeholder fallback fixture" }),
    ...Array.from({ length: 4 }, (_value, index) => card(index + 21, "NEUTRAL")),
  ];
  let saveRequests = 0;
  let nextDeckId = 1;
  let catalogRequests = [];
  let assetRequests = [];
  let assetResponses = [];
  const assetRequestCounts = new Map();

  function deckPayload(raw) {
    const ids = raw.card_ids || [];
    return {
      id: raw.id || "deck-1",
      revision: raw.revision || 1,
      name: raw.name || "New deck",
      hero_id: raw.hero_id || "HERO_01",
      hero: state.heroes.find((item) => item.id === (raw.hero_id || "HERO_01")),
      card_ids: ids,
      cards: ids.map((id) => cards.find((item) => item.id === id)).filter(Boolean),
      complete: ids.length === 30,
    };
  }

  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/api/account/session" && request.method === "GET") {
      return json(response, 200, {
        authenticated: true,
        account: { id: "fixture-account", username: "Collection Fixture" },
        legacy_available: false,
      });
    }
    if (url.pathname === "/api/decks" && request.method === "GET") return json(response, 200, clone(state));
    if (url.pathname === "/api/decks/save" && request.method === "POST") {
      const body = await readBody(request);
    const saved = deckPayload({ ...body, id: body.id || `deck-${nextDeckId++}` });
      const existingIndex = state.decks.findIndex((deck) => deck.id === saved.id);
      if (existingIndex >= 0) state.decks[existingIndex] = saved;
      else state.decks.push(saved);
      saveRequests += 1;
      return json(response, 200, { ...clone(state), saved_id: saved.id });
    }
    if (url.pathname === "/api/decks/delete" && request.method === "POST") {
      const body = await readBody(request);
      state.decks = state.decks.filter((deck) => deck.id !== body.id);
      return json(response, 200, clone(state));
    }
    if (url.pathname === "/api/catalog" && request.method === "GET") {
      catalogRequests.push(url.search);
      const wantedClass = url.searchParams.get("class");
      const query = (url.searchParams.get("q") || "").toLowerCase();
      const filtered = cards.filter((item) => (!wantedClass || item.class === wantedClass) && (!query || `${item.id} ${item.name}`.toLowerCase().includes(query)));
      return json(response, 200, { items: filtered, total: filtered.length, page: 1, page_size: 48, sets: [], classes: [] });
    }
    if (url.pathname.startsWith("/catalog/assets/render/")) {
      const cardId = decodeURIComponent(url.pathname.slice("/catalog/assets/render/".length));
      assetRequests.push(url.pathname);
      const requestCount = (assetRequestCounts.get(cardId) || 0) + 1;
      assetRequestCounts.set(cardId, requestCount);
      if (cardId === "COL_001" && requestCount === 1) {
        assetResponses.push({ path: url.pathname, status: 202 });
        response.writeHead(202);
        response.end();
        return;
      }
      if (cardId === "COL_015") {
        assetResponses.push({ path: url.pathname, status: 404 });
        response.writeHead(404);
        response.end("fixture face unavailable");
        return;
      }
      if (cardId === "COL_016" || cardId === "COL_017") {
        assetResponses.push({ path: url.pathname, status: 404 });
        response.writeHead(404);
        response.end("fixture face unavailable");
        return;
      }
      const body = renderedFace(cardId);
      const isPlaceholder = cardId === "COL_018";
      assetResponses.push({ path: url.pathname, status: 200, placeholder: isPlaceholder });
      response.writeHead(200, {
        "Content-Type": "image/svg+xml",
        "Content-Length": body.length,
        "Cache-Control": "no-store",
        ...(isPlaceholder ? { "X-Asset-Placeholder": "1" } : {}),
      });
      response.end(body);
      return;
    }
    const relative = url.pathname === "/" || url.pathname === "/collection" ? "collection.html" : url.pathname.replace(/^\//, "");
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
    resolve({ server, base: `http://127.0.0.1:${port}/collection`, state, catalogRequests, assetRequests, assetResponses, get saveRequests() { return saveRequests; } });
  }));
}

async function main() {
  const fixture = await startFixture();
  const browser = await chromium.launch({ executablePath: chrome, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(fixture.base);
    await page.locator('[data-testid="collection-layout"]').waitFor({ state: "visible" });
    assert.equal(await page.locator('[data-testid="editor-empty"]').isVisible(), true);
    await page.locator('[data-testid="new-deck"]').click();
    await page.locator('[data-testid="collection-editor"]').waitFor({ state: "visible" });

    const heroFace = page.locator('.collection-hero-option .static-card-face[data-card-id="HERO_01"]');
    await heroFace.waitFor();
    await heroFace.scrollIntoViewIfNeeded();
    try {
      await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="HERO_01"]')?.dataset.imageState === "loaded", null, { timeout: 20000 });
    } catch (error) {
      const faceState = await heroFace.evaluate((face) => {
        const image = face.querySelector("img.static-card-face-image");
        const fallback = face.querySelector(".static-card-face-fallback");
        return {
          connected: face.isConnected,
          faceState: face.dataset.imageState,
          imageState: image?.dataset.imageState,
          imageUrl: image?.src,
          hidden: image?.hidden,
          complete: image?.complete,
          naturalWidth: image?.naturalWidth,
          fallbackVisible: fallback ? getComputedStyle(fallback).display !== "none" && !fallback.hidden : false,
        };
      });
      console.error("HERO_01 face diagnostics", {
        requests: fixture.assetRequests.filter((path) => path.endsWith("/HERO_01")),
        responses: fixture.assetResponses.filter((item) => item.path.endsWith("/HERO_01")),
        faceState,
        pageErrors: errors,
      });
      throw error;
    }
    assert(fixture.assetRequests.includes("/catalog/assets/render/HERO_01"), "hero choices must request rendered card faces");
    await page.waitForFunction(() => {
      const image = document.querySelector('.static-card-face[data-card-id="HERO_01"] .static-card-face-image');
      return image?.complete && image.naturalWidth > 0;
    }, null, { timeout: 20000 });
    const heroImage = await heroFace.locator(".static-card-face-image").evaluate((image) => ({ kind: image.dataset.assetKind, width: image.naturalWidth, height: image.naturalHeight }));
    assert.equal(heroImage.kind, "render");
    assert(heroImage.height / heroImage.width >= 1.35, "hero choices should display full-card render images");

    await page.locator('[data-action="choose-hero"]').first().click();
    await page.locator('[data-testid="card-grid"] [data-action="add-card"]').first().waitFor();
    const firstPoolFace = page.locator('.collection-card-option .static-card-face[data-card-id="COL_001"]');
    await firstPoolFace.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="COL_001"]')?.dataset.imageState === "loaded", null, { timeout: 20000 });
    await page.waitForFunction(() => {
      const image = document.querySelector('.static-card-face[data-card-id="COL_001"] .static-card-face-image');
      return image?.complete && image.naturalWidth > 0;
    }, null, { timeout: 20000 });
    assert(fixture.assetRequests.includes("/catalog/assets/render/COL_001"), "card pool options must request rendered card faces");
    assert(fixture.assetRequests.filter((path) => path === "/catalog/assets/render/COL_001").length >= 2, "a pending pool image should be retried");
    const poolImage = await firstPoolFace.locator(".static-card-face-image").evaluate((image) => ({ kind: image.dataset.assetKind, width: image.naturalWidth, height: image.naturalHeight }));
    assert.equal(poolImage.kind, "render");
    assert(poolImage.height / poolImage.width >= 1.35, "card pool should display full-card render images");
    const poolFaceBox = await firstPoolFace.boundingBox();
    assert(poolFaceBox && poolFaceBox.height / poolFaceBox.width >= 1.35, "card pool faces should keep a portrait card proportion");
    fs.mkdirSync(artifacts, { recursive: true });
    await firstPoolFace.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(artifacts, "collection-rendered-desktop.png") });
    await page.setViewportSize({ width: 375, height: 812 });
    await firstPoolFace.scrollIntoViewIfNeeded();
    const mobileColumns = await page.locator('[data-testid="card-grid"]').evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
    assert.equal(mobileColumns, 2, "mobile card pool should stay compact enough to browse a full page");
    const inspectHeight = await page.locator('.collection-card-inspect[data-card-id="COL_001"]').evaluate((button) => button.getBoundingClientRect().height);
    assert(inspectHeight >= 44, "mobile inspect action should have a usable touch target");
    await page.screenshot({ path: path.join(artifacts, "collection-rendered-mobile.png") });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await firstPoolFace.scrollIntoViewIfNeeded();
    await page.locator('.collection-card-option[data-card-id="COL_015"]').scrollIntoViewIfNeeded();
    const unavailableFace = page.locator('.collection-card-option .static-card-face[data-card-id="COL_015"]');
    await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="COL_015"]')?.dataset.imageState === "unavailable", null, { timeout: 20000 });
    assert(fixture.assetRequests.includes("/catalog/assets/render/COL_015"), "unavailable card face must still use the render endpoint");
    assert.equal(await unavailableFace.locator(".static-card-face-fallback").isVisible(), true, "unavailable card should display structured fallback content");
    assert.match(await unavailableFace.locator(".static-card-face-name").textContent(), /Mage card 15/);

    const spellOption = page.locator('.collection-card-option[data-card-id="COL_016"]');
    const spellFace = spellOption.locator(".static-card-face");
    await spellOption.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="COL_016"]')?.dataset.imageState === "unavailable", null, { timeout: 20000 });
    assert(fixture.assetResponses.some((item) => item.path.endsWith("/COL_016") && item.status === 404), "spell fixture should exercise a missing render");
    assert.equal(await spellFace.locator(".static-card-face-fallback").isVisible(), true, "spell fallback should remain visible without a render");
    assert.equal(await spellFace.locator('[data-stat="attack"]').count(), 0, "spell fallback should omit attack stats");
    assert.equal(await spellFace.locator('[data-stat="health"]').count(), 0, "spell fallback should omit health stats");
    assert.match(await spellFace.locator(".static-card-face-name").textContent(), /Spell fallback fixture/);

    const weaponOption = page.locator('.collection-card-option[data-card-id="COL_017"]');
    const weaponFace = weaponOption.locator(".static-card-face");
    await weaponOption.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="COL_017"]')?.dataset.imageState === "unavailable", null, { timeout: 20000 });
    assert(fixture.assetResponses.some((item) => item.path.endsWith("/COL_017") && item.status === 404), "weapon fixture should exercise a missing render");
    assert.equal(await weaponFace.locator(".static-card-face-fallback").isVisible(), true, "weapon fallback should remain visible without a render");
    assert.equal(await weaponFace.locator('[data-stat="attack"] strong').textContent(), "3");
    assert.equal(await weaponFace.locator('[data-stat="durability"] strong').textContent(), "2", "weapon fallback should show durability");
    assert.equal(await weaponFace.locator('[data-stat="health"]').count(), 0, "weapon fallback should omit health stats");

    const placeholderOption = page.locator('.collection-card-option[data-card-id="COL_018"]');
    const placeholderFace = placeholderOption.locator(".static-card-face");
    await placeholderOption.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="COL_018"]')?.dataset.imageState === "placeholder", null, { timeout: 20000 });
    assert(fixture.assetResponses.some((item) => item.path.endsWith("/COL_018") && item.status === 200 && item.placeholder), "placeholder fixture should return a 200 response with X-Asset-Placeholder");
    assert.equal(await placeholderFace.locator(".static-card-face-fallback").isVisible(), true, "a placeholder 200 response must keep structured fallback visible");
    assert.equal(await placeholderFace.locator(".static-card-face-image").isHidden(), true, "a placeholder response must not display its generic image");

    const heroPowerStats = await page.evaluate(async () => {
      const { createStaticCardFace } = await import('/card_face.js');
      const face = createStaticCardFace({ id: 'HERO_POWER_FIXTURE', name: 'Hero Power', type: 'HERO_POWER', cost: 2, attack: 0, health: 0 });
      return face.querySelectorAll('[data-stat="attack"], [data-stat="health"]').length;
    });
    assert.equal(heroPowerStats, 0, "noncombat card types should not gain fabricated combat stats");

    const inspectButton = page.locator('.collection-card-inspect[data-card-id="COL_016"]');
    await inspectButton.scrollIntoViewIfNeeded();
    const countBeforeInspect = await page.locator('[data-testid="card-count"]').textContent();
    assert.equal(countBeforeInspect, "0 / 30");
    await inspectButton.focus();
    await page.keyboard.press("Enter");
    const cardDetail = page.locator('[data-testid="collection-card-detail"]');
    await cardDetail.waitFor({ state: "visible" });
    assert.match(await page.locator("#collection-card-detail-name").textContent(), /Spell fallback fixture/);
    assert.equal(await page.locator('[data-testid="collection-card-detail-close"]').evaluate((button) => document.activeElement === button), true, "opening details from the keyboard should focus the dialog close button");
    assert.equal(await page.locator('[data-testid="card-count"]').textContent(), countBeforeInspect, "inspecting a card must not add it to the deck");
    assert.equal(await page.locator('[data-testid="selected-list"] .collection-selected-item').count(), 0, "inspection must leave the selected-card list empty");
    await page.keyboard.press("Escape");
    await cardDetail.waitFor({ state: "hidden" });
    assert.equal(await inspectButton.evaluate((button) => document.activeElement === button), true, "closing details with Escape should restore keyboard focus to the inspect button");
    assert.equal(await page.locator('[data-testid="card-count"]').textContent(), countBeforeInspect, "closing inspection must not add the inspected card");

    assert(fixture.catalogRequests.some((query) => query.includes("class=MAGE")), "hero class must filter catalog requests");
    const firstAddButton = page.locator('.collection-card-option[data-card-id="COL_001"]');
    await firstAddButton.scrollIntoViewIfNeeded();
    const firstPoolFaceNode = await firstPoolFace.elementHandle();
    const firstAddButtonNode = await firstAddButton.elementHandle();
    const faceBeforeAdd = await firstPoolFaceNode.evaluate((face) => {
      const image = face.querySelector(".static-card-face-image");
      return {
        imageState: image?.dataset.imageState,
        faceState: face.dataset.imageState,
        imageUrl: image?.src,
      };
    });
    assert.equal(faceBeforeAdd.imageState, "loaded");
    assert(faceBeforeAdd.imageUrl, "loaded pool face should have an image URL before adding");
    await firstAddButton.click();
    assert.match(await page.locator("#collection-status").textContent(), /已加入.*1 \/ 30/, "adding a card should announce the card and new count");
    const faceAfterAdd = await firstPoolFaceNode.evaluate((face) => {
      const image = face.querySelector(".static-card-face-image");
      return {
        connected: face.isConnected,
        imageState: image?.dataset.imageState,
        faceState: face.dataset.imageState,
        imageUrl: image?.src,
      };
    });
    const activeAddButton = page.locator('.collection-card-option[data-card-id="COL_001"]');
    const buttonAfterAdd = await firstAddButtonNode.evaluate((button) => ({
      connected: button.isConnected,
      focused: document.activeElement === button,
    }));
    const activeButtonEnabled = await activeAddButton.isEnabled();
    assert.deepEqual({
      faceConnected: faceAfterAdd.connected,
      imageState: faceAfterAdd.imageState,
      faceState: faceAfterAdd.faceState,
      imageUrl: faceAfterAdd.imageUrl,
      clickedButtonConnected: buttonAfterAdd.connected,
      activeButtonEnabled,
      clickedButtonFocused: buttonAfterAdd.focused,
    }, {
      faceConnected: true,
      imageState: faceBeforeAdd.imageState,
      faceState: faceBeforeAdd.faceState,
      imageUrl: faceBeforeAdd.imageUrl,
      clickedButtonConnected: true,
      activeButtonEnabled: true,
      clickedButtonFocused: true,
    }, "adding one allowed copy should preserve the rendered pool face and keep focus on its button");
    await page.locator('[data-testid="card-count"]').waitFor();
    assert.equal(await page.locator('[data-testid="card-count"]').textContent(), "1 / 30");
    await page.locator('[data-testid="neutral-card-filter"]').click();
    await page.locator('[data-testid="card-grid"] [data-action="add-card"]').first().waitFor();
    assert(fixture.catalogRequests.some((query) => query.includes("class=NEUTRAL")), "neutral tab must filter catalog requests");
    await page.locator('[data-testid="card-search"]').fill("Neutral card");
    await page.waitForTimeout(240);
    assert.match(await page.locator('[data-testid="card-grid"]').textContent(), /Neutral card/);

    await page.locator('[data-testid="card-search"]').fill("");
    await page.locator('[data-testid="class-card-filter"]').click();
    await page.locator('[data-testid="card-grid"] [data-action="add-card"]').first().waitFor();
    for (let index = 0; index < 15; index += 1) {
      const cardId = `COL_${String(index + 1).padStart(3, "0")}`;
      const cardButton = page.locator(`.collection-card-option[data-card-id="${cardId}"]`);
      const copiesToAdd = index === 0 ? 1 : 2;
      for (let copy = 0; copy < copiesToAdd; copy += 1) {
        await cardButton.click();
        await page.locator('[data-testid="card-count"]').waitFor();
      }
    }
    assert.equal(await page.locator('[data-testid="card-count"]').textContent(), "30 / 30");
    assert.equal(await page.locator('[data-testid="mana-curve"] .collection-mana-column').count(), 8);
    const costs = await page.locator('[data-testid="selected-list"] .collection-selected-cost').evaluateAll((nodes) => nodes.map((node) => Number(node.textContent)));
    assert.deepEqual(costs, [...costs].sort((a, b) => a - b));

    await page.locator('[data-testid="deck-name"]').fill("Browser deck");
    await page.locator('[data-testid="save-deck"]').click();
    await page.locator('[data-testid="use-in-battle"]').waitFor({ state: "visible" });
    assert.match(await page.locator('[data-testid="use-in-battle"]').getAttribute("href"), /[?]deck=deck-1/);
    assert(fixture.saveRequests >= 1);
    const originalDeck = clone(fixture.state.decks.find((deck) => deck.id === "deck-1"));
    assert(originalDeck, "the first saved deck should be present in the fixture state");

    let savedHeroDialogMessage = "";
    page.once("dialog", async (dialog) => {
      savedHeroDialogMessage = dialog.message();
      await dialog.accept();
    });
    await page.locator('[data-action="choose-hero"][data-hero-id="HERO_02"]').click();
    assert.match(savedHeroDialogMessage, /新建.*空卡组.*保留.*已保存.*卡组/);
    assert.equal(await page.locator('[data-testid="deck-name"]').inputValue(), "新卡组");
    assert.equal(await page.locator('[data-testid="card-count"]').textContent(), "0 / 30");
    assert.equal(await page.locator('[data-testid="selected-list"] .collection-selected-item').count(), 0);
    assert.equal(await page.locator('[data-testid="deck-list"] .collection-deck-select').count(), 1, "switching a saved deck hero should leave the saved deck in the list");
    assert.equal(await page.locator('[data-testid="deck-list"] .collection-deck-item.is-selected').count(), 0, "the new draft should not select the old saved deck");

    await page.locator('[data-testid="save-deck"]').click();
    await page.locator('[data-testid="deck-list"] .collection-deck-select').filter({ hasText: "新卡组" }).waitFor();
    const savedDecksAfterHeroSwitch = fixture.state.decks.map(clone);
    assert.equal(savedDecksAfterHeroSwitch.length, 2);
    const newHeroDeck = savedDecksAfterHeroSwitch.find((deck) => deck.id !== originalDeck.id);
    assert(newHeroDeck, "switching hero from a saved deck should create a second saved deck");
    assert.notEqual(newHeroDeck.id, originalDeck.id);
    assert.equal(newHeroDeck.hero_id, "HERO_02");
    assert.deepEqual(newHeroDeck.card_ids, []);
    assert.equal(newHeroDeck.name, "新卡组");
    assert.deepEqual(savedDecksAfterHeroSwitch.find((deck) => deck.id === originalDeck.id), originalDeck, "the original saved deck must retain its hero and cards");

    fs.mkdirSync(artifacts, { recursive: true });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(artifacts, "collection-desktop.png") });
    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, "collection editor must fit a narrow viewport");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(artifacts, "collection-mobile.png") });
    await page.setViewportSize({ width: 1440, height: 1000 });

    await page.locator('[data-testid="new-deck"]').click();
    await page.locator('[data-testid="deck-name"]').fill("Second deck");
    await page.locator('[data-action="choose-hero"]').first().click();
    await page.locator('[data-testid="save-deck"]').click();
    await page.locator('[data-testid="deck-list"] .collection-deck-select').filter({ hasText: "Second deck" }).waitFor();
    assert.match(await page.locator('[data-testid="deck-list"]').textContent(), /Second deck/);
    await page.locator('[data-testid="deck-list"] .collection-deck-select').filter({ hasText: "Browser deck" }).click();
    assert.match(await page.locator('[data-testid="deck-name"]').inputValue(), /Browser deck/);

    await page.reload();
    await page.locator('[data-testid="deck-list"] .collection-deck-select').first().waitFor();
    assert.match(await page.locator('[data-testid="deck-list"]').textContent(), /Browser deck/);
    assert.equal(await page.locator('[data-testid="selected-list"] .collection-selected-item').count(), 15, "duplicate card metadata must render once per card ID");
    assert.equal((await page.locator('[data-testid="mana-curve"] .collection-mana-column').evaluateAll((nodes) => nodes.reduce((sum, node) => sum + Number(node.dataset.count), 0))), 30);
    await page.locator('[data-testid="delete-deck"]').click();
    await page.locator('[data-testid="delete-deck"]').click();
    await page.locator('[data-testid="delete-deck"]').click();
    await page.locator('[data-testid="editor-empty"]').waitFor({ state: "visible" });
    assert.equal(fixture.state.decks.length, 0);

    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true, "collection must fit a narrow viewport");
    assert.deepEqual(errors, []);
    console.log("collection browser acceptance passed");
  } finally {
    await browser.close();
    fixture.server.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
