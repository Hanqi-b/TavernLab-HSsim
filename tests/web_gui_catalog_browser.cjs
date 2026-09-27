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
    let aRequests = 0;
    let delayA = false;
    const assetRequests = [];
    const assetResponses = [];
    const image = (color) => Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120" viewBox="0 0 80 120"><rect x="1" y="1" width="78" height="118" rx="7" fill="#171b2b" stroke="${color}" stroke-width="3"/><circle cx="40" cy="50" r="24" fill="${color}"/><path d="M10 88h60v18H10z" fill="#e3c079"/></svg>`);
    await page.route("**/catalog/assets/**", async (route) => {
      const requestUrl = new URL(route.request().url());
      const cardId = decodeURIComponent(requestUrl.pathname.split("/").pop());
      assetRequests.push(requestUrl.pathname);
      if (cardId === "AT_003") {
        aRequests += 1;
        if (aRequests <= 3) {
          assetResponses.push({ path: requestUrl.pathname, status: 202 });
          return route.fulfill({ status: 202, body: "" });
        }
        if (delayA) await new Promise((resolve) => setTimeout(resolve, 1000));
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
    fs.mkdirSync(artifacts, { recursive: true });
    await page.screenshot({ path: path.join(artifacts, "catalog-desktop.png") });

    await page.locator('[data-testid="catalog-search"]').fill("Fallen Hero");
    await page.locator('.catalog-card[data-card-id="AT_003"]').waitFor({ timeout: 20000 });
    assert.equal(await page.locator(".catalog-card[data-card-id]").count(), 1);
    await page.locator('.catalog-card[data-card-id="AT_003"]').scrollIntoViewIfNeeded();
    try {
      await page.waitForFunction(() => document.querySelector('.static-card-face[data-card-id="AT_003"]')?.dataset.imageState === "loaded", null, { timeout: 20000 });
    } catch (error) {
      console.error("AT_003 face diagnostics", {
        requests: assetRequests.filter((path) => path.endsWith("/AT_003")),
        responses: assetResponses.filter((item) => item.path.endsWith("/AT_003")),
        face: await page.locator('.static-card-face[data-card-id="AT_003"]').evaluate((node) => {
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
    assert(aRequests >= 4, "a pending image response must be retried beyond one second");
    assert(assetRequests.includes("/catalog/assets/render/AT_003"), "catalog faces must request full rendered card assets");
    const cardFace = page.locator('.static-card-face[data-card-id="AT_003"]');
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
    assert.equal(await page.locator('.catalog-card[data-card-id="AT_003"] .catalog-script-badge').count(), 1, "cards must expose Python script status");
    await page.locator('[data-testid="catalog-set"]').selectOption("TGT");
    await page.locator('[data-testid="catalog-class"]').selectOption("MAGE");
    await page.locator('.catalog-card[data-card-id="AT_003"]').waitFor({ timeout: 20000 });
    await page.locator('.catalog-card[data-card-id="AT_003"]').click();
    await page.locator('[data-testid="catalog-detail"]').waitFor({ state: "visible" });
    assert.match(await page.locator("#catalog-detail-id").textContent(), /AT_003/);
    assert(assetRequests.includes("/catalog/assets/render/AT_003"), "detail cards must request rendered card assets");
    const detailBox = await page.locator("#catalog-detail-art").boundingBox();
    assert(detailBox && detailBox.width <= 221, "detail card art should stay within the compact width limit");
    assert.equal(await page.locator("#catalog-script-note").getAttribute("hidden"), null, "detail must explain Python script status");
    await page.locator('#catalog-detail-image[data-image-state="loaded"]').waitFor({ timeout: 20000 });
    const detailImageUrl = await page.locator("#catalog-detail-image").getAttribute("src");
    const refreshedList = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/catalog" && response.url().includes("q=AT_003"),
    );
    await page.evaluate(() => {
      const search = document.getElementById("catalog-search");
      search.value = "AT_003";
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await refreshedList;
    await page.waitForFunction(() => document.getElementById("catalog-grid")?.getAttribute("aria-busy") === "false");
    const detailImageStillAvailable = await page.evaluate(async (url) => {
      try { return (await fetch(url)).ok; } catch (_error) { return false; }
    }, detailImageUrl);
    assert(detailImageStillAvailable, "refreshing the grid must not revoke the open detail image");
    await page.locator("#catalog-dialog-close").click();
    await page.locator("#catalog-locale-enUS").click();
    await page.locator('.catalog-card[data-card-id="AT_003"]').click();
    await page.waitForFunction(() => document.getElementById("catalog-detail-name")?.textContent === "Fallen Hero", null, { timeout: 20000 });
    await page.locator("#catalog-dialog-close").click();

    await page.locator('[data-testid="catalog-search"]').fill("HERO_01c");
    await page.locator('[data-testid="catalog-set"]').selectOption("");
    await page.locator('[data-testid="catalog-class"]').selectOption("");
    await page.locator("#catalog-empty").waitFor({ state: "visible", timeout: 20000 });
    await page.locator(".catalog-scope-toggle").click();
    assert.equal(await page.locator('[data-testid="catalog-set"] option[value="HEROES"]').count(), 1, "heroes must have their own catalog category");
    await page.locator('[data-testid="catalog-set"]').selectOption("HERO_SKINS");
    await page.locator('.catalog-card[data-card-id="HERO_01c"]').waitFor({ timeout: 20000 });
    assert.equal(await page.locator('.catalog-card[data-card-id="HERO_01c"]').getAttribute("data-catalog-set"), "HERO_SKINS", "hero skins should retain their source category");
    await page.locator('[data-testid="catalog-search"]').fill("HERO_01");
    await page.locator('[data-testid="catalog-set"]').selectOption("HEROES");
    await page.locator('.catalog-card[data-card-id="HERO_01"]').waitFor({ timeout: 20000 });
    assert.equal(await page.locator('.catalog-card[data-card-id="HERO_01"]').getAttribute("data-catalog-set"), "HEROES", "starting heroes should use the Heroes category");
    await page.locator('[data-testid="catalog-search"]').fill("BOT_238");
    await page.locator('[data-testid="catalog-set"]').selectOption("BOOMSDAY");
    await page.locator('.catalog-card[data-card-id="BOT_238"]').waitFor({ timeout: 20000 });
    assert.equal(await page.locator('.catalog-card[data-card-id="BOT_238"]').getAttribute("data-catalog-set"), "BOOMSDAY", "playable hero cards should stay in their expansion");

    await page.locator('[data-testid="catalog-search"]').fill("CS2_231");
    await page.locator('[data-testid="catalog-set"]').selectOption("");
    await page.locator('[data-testid="catalog-class"]').selectOption("NEUTRAL");
    await page.locator('.catalog-card[data-card-id="CS2_231"]').waitFor({ timeout: 20000 });

    await page.locator('[data-testid="catalog-search"]').fill("");
    await page.locator('[data-testid="catalog-class"]').selectOption("");
    await page.locator('[data-testid="catalog-next"]').click();
    await page.waitForFunction(() => /2/.test(document.getElementById("catalog-page-label")?.textContent || ""));

    // A delayed response from a closed card must not replace the next card's art.
    delayA = true;
    await page.locator('[data-testid="catalog-search"]').fill("AT_003");
    await page.locator('.catalog-card[data-card-id="AT_003"]').click();
    await page.locator("#catalog-dialog-close").click();
    await page.locator('[data-testid="catalog-search"]').fill("CS2_231");
    await page.locator('.catalog-card[data-card-id="CS2_231"]').click();
    await page.locator('#catalog-detail-image[data-image-state="loaded"]').waitFor({ timeout: 20000 });
    await page.waitForTimeout(1200);
    const detailArt = await page.locator("#catalog-detail-image").evaluate(async (node) => {
      const response = await fetch(node.src);
      return response.text();
    });
    assert.match(detailArt, /blue/, "stale art from the previous card replaced the current card");
    await page.locator("#catalog-dialog-close").click();

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
