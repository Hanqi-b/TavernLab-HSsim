#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const python = process.env.FIREPLACE_GUI_PYTHON || process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-web-gui-artifacts");

function startServer(testDataRoot) {
  const child = spawn(python, ["-u", "-m", "fireplace.web_gui", "--port", "0"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      FIREPLACE_ACCOUNT_STATE: path.join(testDataRoot, "accounts.sqlite3"),
      FIREPLACE_ACCOUNT_DATA_ROOT: path.join(testDataRoot, "users"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.setEncoding("utf8");
  const lines = readline.createInterface({ input: child.stdout });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("catalog server did not start")), 30000);
    lines.on("line", (line) => {
      const match = line.match(/^Open (http:\/\/127\.0\.0\.1:\d+\/)$/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("exit", (code) => { clearTimeout(timer); reject(new Error(`server exited: ${code}`)); });
  });
  return { child, ready };
}

async function waitForCards(page) {
  await page.waitForFunction(() => {
    const grid = document.getElementById("catalog-grid");
    return grid?.getAttribute("aria-busy") === "false" &&
      (grid.querySelector(".catalog-card[data-card-id]") || !document.getElementById("catalog-empty")?.hidden);
  }, null, { timeout: 20000 });
}

async function frameFace(page, face, top = 100) {
  await face.evaluate((node, desiredTop) => {
    const previousBehavior = document.documentElement.style.scrollBehavior;
    document.documentElement.style.scrollBehavior = "auto";
    window.scrollTo(0, Math.max(0, window.scrollY + node.getBoundingClientRect().top - desiredTop));
    document.documentElement.style.scrollBehavior = previousBehavior;
  }, top);
}

async function waitForCatalogPayload(records, setId, pageNumber, query = null) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const record = [...records].reverse().find((item) =>
      item.url.searchParams.get("set") === setId &&
      item.url.searchParams.get("page") === String(pageNumber) &&
      item.url.searchParams.get("q") === query,
    );
    if (record) return record;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`catalog response not observed for ${setId}, page ${pageNumber}`);
}

function assertCollectibleNeutralPage(payload) {
  assert(payload.items.length > 0, "a catalog page should contain cards");
  for (const card of payload.items) {
    assert.equal(card.collectible, true, `${card.id} must be collectible`);
    assert.deepEqual(card.classes, ["NEUTRAL"], `${card.id} must be neutral only`);
  }
  const costs = payload.items.map((card) => card.cost);
  assert.deepEqual(costs, [...costs].sort((a, b) => a - b), "cards on each page must be sorted by mana cost");
}

function assertCatalogQuery(record, setId, pageNumber) {
  assert.equal(record.url.searchParams.get("set"), setId);
  assert.equal(record.url.searchParams.get("page"), String(pageNumber));
  assert.equal(record.url.searchParams.get("scope"), "collectible");
  assert.equal(record.url.searchParams.get("class"), "NEUTRAL");
  assert.equal(record.url.searchParams.get("sort"), "cost");
  assertCollectibleNeutralPage(record.payload);
}

function catalogApiUrl(url) {
  return url.pathname === "/api/catalog";
}

async function main() {
  const testDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), "fireplace-catalog-browser-"));
  const server = startServer(testDataRoot);
  let browser;
  try {
    const base = await server.ready;
    browser = await chromium.launch({ executablePath: chrome, headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    let retryCardRequests = 0;
    let delayRetryCard = false;
    const assetRequests = [];
    const assetResponses = [];
    const catalogResponses = [];
    const qualityStatusById = new Map([["EX1_015", "GREEN"]]);
    const qualityCardIds = {};
    const image = (color) => Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120" viewBox="0 0 80 120"><rect x="1" y="1" width="78" height="118" rx="7" fill="#171b2b" stroke="${color}" stroke-width="3"/><circle cx="40" cy="50" r="24" fill="${color}"/><path d="M10 88h60v18H10z" fill="#e3c079"/></svg>`);
    await page.route("**/api/catalog?*", async (route) => {
      const url = new URL(route.request().url());
      const response = await route.fetch();
      const payload = JSON.parse((await response.body()).toString("utf8"));
      if (response.ok()) {
        if (url.searchParams.get("set") === "BASIC" && url.searchParams.get("page") === "1" && !url.searchParams.has("q")) {
          const statusCards = payload.items.filter((card) => card.id !== "EX1_015").slice(0, 3);
          ["GREEN", "YELLOW", "RED"].forEach((status, index) => {
            const card = statusCards[index];
            if (!card) return;
            qualityStatusById.set(card.id, status);
            qualityCardIds[status] = card.id;
          });
        }
        payload.items = payload.items.map((card) => {
          if (qualityStatusById.has(card.id)) card.quality_status = qualityStatusById.get(card.id);
          return card;
        });
        catalogResponses.push({ url, payload });
      }
      await route.fulfill({ response, body: JSON.stringify(payload) });
    });
    await page.route("**/api/catalog/cards/**", async (route) => {
      const response = await route.fetch();
      const payload = JSON.parse((await response.body()).toString("utf8"));
      const card = payload.card && typeof payload.card === "object" ? payload.card : payload;
      if (qualityStatusById.has(card.id)) card.quality_status = qualityStatusById.get(card.id);
      await route.fulfill({ response, body: JSON.stringify(payload) });
    });
    await page.route("**/catalog/assets/**", async (route) => {
      const requestUrl = new URL(route.request().url());
      const cardId = decodeURIComponent(requestUrl.pathname.split("/").pop());
      assetRequests.push(requestUrl.pathname);
      if (cardId === "EX1_015") {
        retryCardRequests += 1;
        if (retryCardRequests <= 3) {
          assetResponses.push({ path: requestUrl.pathname, status: 202 });
          return route.fulfill({ status: 202, body: "" });
        }
        if (delayRetryCard) await new Promise((resolve) => setTimeout(resolve, 1000));
        assetResponses.push({ path: requestUrl.pathname, status: 200 });
        return route.fulfill({ status: 200, contentType: "image/svg+xml", body: image("red") });
      }
      if (cardId === "CS2_231") {
        assetResponses.push({ path: requestUrl.pathname, status: 200 });
        return route.fulfill({ status: 200, contentType: "image/svg+xml", body: image("blue") });
      }
      assetResponses.push({ path: requestUrl.pathname, status: 404 });
      return route.fulfill({ status: 404, body: "" });
    });

    // The catalog is public even when the account-protected game pages are not.
    await page.goto(new URL("/cards", base).toString());
    await page.waitForURL(`${base}cards`);
    await waitForCards(page);
    assert((await page.locator(".catalog-card[data-card-id]").count()) > 0);
    const classOptions = await page.locator('[data-testid="catalog-class"] option').evaluateAll((options) =>
      options.map((option) => option.value),
    );
    assert.deepEqual(classOptions, [
      "NEUTRAL", "DRUID", "HUNTER", "MAGE", "PALADIN", "PRIEST",
      "ROGUE", "SHAMAN", "WARLOCK", "WARRIOR", "DEMONHUNTER",
    ], "card viewing must offer Neutral and each profession without an all-classes option");
    assert.equal(await page.locator('[data-testid="catalog-class"]').inputValue(), "NEUTRAL");
    assert.equal(await page.locator(".catalog-scope-toggle, [data-testid='catalog-scope']").count(), 0,
      "the catalog must not expose an all-XML scope control");
    const setOptions = await page.locator('[data-testid="catalog-set"] option').evaluateAll((options) =>
      options.map((option) => option.value),
    );
    assert(!setOptions.includes(""), "the catalog must not expose an all-sets option");
    assert.equal(await page.locator('[data-testid="catalog-set"]').inputValue(), "BASIC",
      "the catalog should open on the Basic set by default");
    assert(setOptions.includes("EXPERT1"), "a concrete expansion should remain selectable");
    const basicResponse = await waitForCatalogPayload(catalogResponses, "BASIC", 1);
    assertCatalogQuery(basicResponse, "BASIC", 1);
    assert(basicResponse.payload.total > 0, "the default Basic set should contain collectible Neutral cards");
    assert.deepEqual(Object.keys(qualityCardIds).sort(), ["GREEN", "RED", "YELLOW"], "catalog fixture should cover all three quality statuses");
    for (const [status, label] of [["GREEN", ""], ["YELLOW", "效果待验证"], ["RED", "效果存在问题"]]) {
      const cardId = qualityCardIds[status];
      const card = page.locator(`.catalog-card[data-card-id="${cardId}"]`);
      assert.equal(await card.getAttribute("data-quality-status"), status, `${status} catalog card should expose its status`);
      const gridBadge = card.locator(".catalog-quality-badge");
      if (status === "GREEN") assert.equal(await gridBadge.count(), 0, "GREEN cards should have no extra catalog alert");
      else assert.equal((await gridBadge.textContent()).trim(), label, `${status} grid alert should use the Chinese label`);
      assert.equal(await card.locator(".catalog-script-badge").count(), 0, "catalog cards must not show Python script labels");
      await card.click();
      await page.locator('[data-testid="catalog-detail"]').waitFor({ state: "visible" });
      const detailBadge = page.locator("#catalog-detail-badges .catalog-quality-badge");
      if (status === "GREEN") assert.equal(await detailBadge.count(), 0, "GREEN details should have no extra catalog alert");
      else assert.equal((await detailBadge.textContent()).trim(), label, `${status} detail alert should use the Chinese label`);
      await page.locator("#catalog-dialog-close").click();
    }
    assert.equal(await page.locator(".catalog-script-badge").count(), 0, "the catalog must not show Python script labels");
    fs.mkdirSync(artifacts, { recursive: true });
    await page.screenshot({ path: path.join(artifacts, "catalog-desktop.png") });

    const mageResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("class") === "MAGE" && url.searchParams.get("set") === "BASIC";
    });
    await page.locator('[data-testid="catalog-class"]').selectOption("MAGE");
    const mageCards = await (await mageResponse).json();
    assert(mageCards.items.length > 0, "a profession option should show its own collectible cards");
    assert(mageCards.items.every((card) => card.collectible && card.classes.includes("MAGE")));

    const mageExpertResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("class") === "MAGE" && url.searchParams.get("set") === "EXPERT1";
    });
    await page.locator('[data-testid="catalog-set"]').selectOption("EXPERT1");
    await mageExpertResponse;

    const demonHunterResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("class") === "DEMONHUNTER" && url.searchParams.get("set") === "BASIC";
    });
    await page.locator('[data-testid="catalog-class"]').selectOption("DEMONHUNTER");
    const demonHunterCards = await (await demonHunterResponse).json();
    assert(demonHunterCards.items.length > 0, "Demon Hunter should switch to a set containing its collectible cards");
    assert(demonHunterCards.items.every((card) => card.collectible && card.classes.includes("DEMONHUNTER")));
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    assert.equal(await page.locator('[data-testid="catalog-set"]').inputValue(), "BASIC");

    const backToNeutral = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("class") === "NEUTRAL" && url.searchParams.get("set") === "BASIC";
    });
    await page.locator('[data-testid="catalog-class"]').selectOption("NEUTRAL");
    await backToNeutral;
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");

    const retrySearchResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("set") === "BASIC" &&
        url.searchParams.get("q") === "EX1_015";
    });
    await page.locator('[data-testid="catalog-search"]').fill("EX1_015");
    await retrySearchResponse;
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    await page.locator('.catalog-card[data-card-id="EX1_015"]').waitFor({ timeout: 20000 });
    assert.equal(await page.locator(".catalog-card[data-card-id]").count(), 1);
    await page.locator('.catalog-card[data-card-id="EX1_015"]').scrollIntoViewIfNeeded();
    try {
      await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="EX1_015"]')?.dataset.imageState === "loaded", null, { timeout: 20000 });
    } catch (error) {
      console.error("EX1_015 face diagnostics", {
        requests: assetRequests.filter((path) => path.endsWith("/EX1_015")),
        responses: assetResponses.filter((item) => item.path.endsWith("/EX1_015")),
        face: await page.locator('.static-card-face[data-card-id="EX1_015"]').evaluate((node) => {
          const image = node.querySelector("img.static-card-face-image");
          const fallback = node.querySelector(".static-card-face-fallback");
          return {
            connected: node.isConnected,
            faceState: node.dataset.imageState,
            imageState: image?.dataset.imageState,
            imageUrl: image?.src,
            hidden: image?.hidden,
            complete: image?.complete,
            naturalWidth: image?.naturalWidth,
            fallbackVisible: fallback ? getComputedStyle(fallback).display !== "none" && !fallback.hidden : false,
          };
        }),
        pageErrors,
      });
      throw error;
    }
    assert(retryCardRequests >= 4, "a pending image response must be retried beyond one second");
    assert(assetRequests.includes("/catalog/assets/render/EX1_015"), "catalog faces must request full rendered card assets");
    const cardFace = page.locator('.static-card-face[data-card-id="EX1_015"]');
    assert.equal(await cardFace.getAttribute("data-image-state"), "loaded", "catalog card face should finish loading its render");
    const faceBox = await cardFace.boundingBox();
    assert(faceBox && faceBox.height / faceBox.width >= 1.35, "catalog card face should keep a portrait card proportion");
    const faceImage = await cardFace.locator(".static-card-face-image").evaluate((node) => ({ width: node.naturalWidth, height: node.naturalHeight, kind: node.dataset.assetKind }));
    assert.equal(faceImage.kind, "render");
    assert(faceImage.height / faceImage.width >= 1.35, "catalog face should display a full-card render image");
    await frameFace(page, cardFace, 160);
    await page.screenshot({ path: path.join(artifacts, "catalog-rendered-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await frameFace(page, cardFace, 100);
    await page.screenshot({ path: path.join(artifacts, "catalog-rendered-mobile.png") });
    await page.setViewportSize({ width: 1440, height: 900 });
    await frameFace(page, cardFace, 160);
    assert.equal(await page.locator('.catalog-card[data-card-id="EX1_015"] .catalog-script-badge').count(), 0, "cards must not expose Python script status");
    const retryResponse = [...catalogResponses].reverse().find((item) => item.url.searchParams.get("q") === "EX1_015");
    assert(retryResponse, "search should issue a catalog query");
    assertCatalogQuery(retryResponse, "BASIC", 1);
    assert.equal(retryResponse.payload.total, 1);
    await page.locator('.catalog-card[data-card-id="EX1_015"]').click();
    await page.locator('[data-testid="catalog-detail"]').waitFor({ state: "visible" });
    assert.match(await page.locator("#catalog-detail-id").textContent(), /EX1_015/);
    assert(assetRequests.includes("/catalog/assets/render/EX1_015"), "detail cards must request rendered card assets");
    const detailBox = await page.locator("#catalog-detail-art").boundingBox();
    assert(detailBox && detailBox.width <= 221, "detail card art should stay within the compact width limit");
    assert.equal(await page.locator("#catalog-script-note").count(), 0, "detail must not include the obsolete Python script note");
    await page.locator('#catalog-detail-image[data-image-state="loaded"]').waitFor({ timeout: 20000 });
    const detailImageUrl = await page.locator("#catalog-detail-image").getAttribute("src");
    const refreshedList = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/catalog" && response.url().includes("q=CS2_171"),
    );
    await page.evaluate(() => {
      const search = document.getElementById("catalog-search");
      search.value = "CS2_171";
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await refreshedList;
    await page.locator('.catalog-card[data-card-id="CS2_171"]').waitFor({ timeout: 20000 });
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    const detailImageStillAvailable = await page.evaluate(async (url) => {
      try { return (await fetch(url)).ok; } catch (_error) { return false; }
    }, detailImageUrl);
    assert(detailImageStillAvailable, "refreshing the grid must not revoke the open detail image");
    await page.locator("#catalog-dialog-close").click();
    await page.locator("#catalog-locale-enUS").click();
    await page.locator('.catalog-card[data-card-id="CS2_171"]').click();
    await page.waitForFunction(() => document.getElementById("catalog-detail-name")?.textContent === "Stonetusk Boar", null, { timeout: 20000 });
    await page.locator("#catalog-dialog-close").click();
    for (const [status, label] of [["GREEN", ""], ["YELLOW", "Effects not fully verified"], ["RED", "Known effect issues"]]) {
      const cardId = qualityCardIds[status];
      const statusResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return catalogApiUrl(url) && url.searchParams.get("q") === cardId;
      });
      await page.locator('[data-testid="catalog-search"]').fill(cardId);
      await statusResponse;
      await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
      const card = page.locator(`.catalog-card[data-card-id="${cardId}"]`);
      await card.waitFor({ timeout: 20000 });
      const gridBadge = card.locator(".catalog-quality-badge");
      if (status === "GREEN") assert.equal(await gridBadge.count(), 0, "GREEN cards should have no extra English catalog alert");
      else assert.equal((await gridBadge.textContent()).trim(), label, `${status} grid alert should use the English label`);
      await card.click();
      await page.locator('[data-testid="catalog-detail"]').waitFor({ state: "visible" });
      const detailBadge = page.locator("#catalog-detail-badges .catalog-quality-badge");
      if (status === "GREEN") assert.equal(await detailBadge.count(), 0, "GREEN details should have no extra English catalog alert");
      else assert.equal((await detailBadge.textContent()).trim(), label, `${status} detail alert should use the English label`);
      await page.locator("#catalog-dialog-close").click();
    }

    // A delayed response from a closed Neutral card must not replace the next card's art.
    await page.locator('[data-testid="catalog-search"]').fill("EX1_015");
    await page.locator('.catalog-card[data-card-id="EX1_015"]').waitFor({ timeout: 20000 });
    delayRetryCard = true;
    const priorRetryRequests = retryCardRequests;
    await page.locator('.catalog-card[data-card-id="EX1_015"]').click();
    await page.locator("#catalog-detail-image").waitFor({ state: "attached", timeout: 20000 });
    const requestDeadline = Date.now() + 20000;
    while (retryCardRequests <= priorRetryRequests && Date.now() < requestDeadline) {
      await page.waitForTimeout(25);
    }
    assert(retryCardRequests > priorRetryRequests, "the delayed previous card image request should be in flight");
    await page.locator("#catalog-dialog-close").click();
    await page.locator('[data-testid="catalog-set"]').selectOption("EXPERT1");
    await page.locator('[data-testid="catalog-search"]').fill("CS2_231");
    await page.locator('.catalog-card[data-card-id="CS2_231"]').waitFor({ timeout: 20000 });
    await page.locator('.catalog-card[data-card-id="CS2_231"]').click();
    await page.locator('#catalog-detail-image[data-image-state="loaded"]').waitFor({ timeout: 20000 });
    await page.waitForTimeout(1200);
    const detailArt = await page.locator("#catalog-detail-image").evaluate(async (node) => {
      const response = await fetch(node.src);
      return response.text();
    });
    assert.match(detailArt, /blue/, "stale art from the previous card replaced the current card");
    await page.locator("#catalog-dialog-close").click();

    const expertListResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/catalog" && url.searchParams.get("set") === "EXPERT1" &&
        url.searchParams.get("page") === "1" && url.searchParams.get("q") === null;
    });
    await page.locator('[data-testid="catalog-search"]').fill("");
    await expertListResponse;
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    await page.locator('[data-testid="catalog-next"]').click();
    const expertPage2 = await waitForCatalogPayload(catalogResponses, "EXPERT1", 2);
    assertCatalogQuery(expertPage2, "EXPERT1", 2);
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    await page.locator('[data-testid="catalog-next"]').click();
    const expertPage3 = await waitForCatalogPayload(catalogResponses, "EXPERT1", 3);
    assertCatalogQuery(expertPage3, "EXPERT1", 3);
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    const expertPage1 = await waitForCatalogPayload(catalogResponses, "EXPERT1", 1);
    assertCatalogQuery(expertPage1, "EXPERT1", 1);
    const expertCards = [...expertPage1.payload.items, ...expertPage2.payload.items, ...expertPage3.payload.items];
    assert.equal(expertCards.length, expertPage1.payload.total, "pagination should cover every card in the selected set");
    const expertCosts = expertCards.map((card) => card.cost);
    assert.deepEqual(expertCosts, [...expertCosts].sort((a, b) => a - b),
      "mana cost order must remain ascending across page boundaries");

    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert(overflow <= 1, `catalog overflows narrow viewport by ${overflow}px`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(artifacts, "catalog-mobile.png") });
    await page.locator('[data-testid="catalog-back"]').click();
    await page.waitForURL(/\/account\?next=/);
    assert.equal(pageErrors.length, 0, pageErrors.join("\n"));
    console.log("catalog browser acceptance passed");
  } finally {
    if (browser) await browser.close();
    server.child.kill("SIGTERM");
    fs.rmSync(testDataRoot, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
