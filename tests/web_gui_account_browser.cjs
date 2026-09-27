#!/usr/bin/env node
/*
 * CLI-backed browser acceptance for local accounts and account data isolation.
 * Every run uses temporary account and user-data roots; no real saved data is
 * read or changed.
 */

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
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || path.join(os.tmpdir(), "fireplace-web-gui-artifacts");

function startServer(dataRoot) {
  const child = spawn(python, ["-u", "-m", "fireplace.web_gui", "--port", "0"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      FIREPLACE_ACCOUNT_STATE: path.join(dataRoot, "accounts.sqlite3"),
      FIREPLACE_ACCOUNT_DATA_ROOT: path.join(dataRoot, "users"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  const lines = readline.createInterface({ input: child.stdout });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`server startup timed out\n${logs.join("")}`)), 30000);
    lines.on("line", (line) => {
      logs.push(`${line}\n`);
      const match = line.match(/^Open (http:\/\/127\.0\.0\.1:\d+\/)$/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      reject(new Error(`server exited before ready (code=${code}, signal=${signal})\n${logs.join("")}`));
    });
  });
  return { child, ready };
}

async function api(page, route, { method = "GET", body } = {}) {
  return page.evaluate(async ({ route, method, body }) => {
    const response = await fetch(route, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: body === undefined ? { Accept: "application/json" } : {
        Accept: "application/json", "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* empty response */ }
    return { status: response.status, payload };
  }, { route, method, body });
}

async function registerFromProtectedPage(page, base, username, password, protectedPath) {
  await page.goto(new URL(protectedPath, base).toString(), { waitUntil: "domcontentloaded" });
  await page.waitForURL((url) => new URL(url).pathname === "/account", { timeout });
  const next = new URL(page.url()).searchParams.get("next");
  assert.equal(next, protectedPath, `${protectedPath} should survive the login redirect`);
  if (username === "Account Alice") {
    fs.mkdirSync(artifacts, { recursive: true });
    await page.screenshot({ path: path.join(artifacts, "account-login-desktop.png") });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.screenshot({ path: path.join(artifacts, "account-login-mobile.png") });
    await page.setViewportSize({ width: 1280, height: 800 });
  }

  await page.locator("#register-tab").click();
  await page.locator("#account-username").fill(username);
  await page.locator("#account-password").fill(password);
  await page.locator("#account-confirm-password").fill(password);
  await page.locator("#account-submit").click();
  await page.waitForURL((url) => new URL(url).pathname === protectedPath, { timeout });
  const cookies = await page.context().cookies(base);
  const sessionCookie = cookies.find((cookie) => cookie.name === "fireplace_session");
  assert(sessionCookie, `${username} should receive an authenticated session cookie`);
  assert.equal(sessionCookie.httpOnly, true, "session cookie must be HttpOnly");
  await page.locator('[data-testid="account-toolbar"]').waitFor({ state: "visible", timeout });
  const session = await api(page, "/api/account/session");
  assert.equal(session.status, 200);
  assert.equal(session.payload.authenticated, true);
  assert.equal(session.payload.account.username, username);
}

async function main() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), "fireplace-account-browser-"));
  const server = startServer(dataRoot);
  let browser;
  try {
    const base = await server.ready;
    browser = await chromium.launch({
      headless: process.env.FIREPLACE_GUI_HEADFUL !== "1",
      executablePath: chrome,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });

    const publicContext = await browser.newContext();
    const publicPage = await publicContext.newPage();
    await publicPage.goto(new URL("/cards", base).toString(), { waitUntil: "domcontentloaded" });
    await publicPage.waitForURL(/\/cards$/);
    await publicPage.locator("#catalog-grid").waitFor({ state: "visible", timeout });
    await publicContext.close();

    const aliceContext = await browser.newContext();
    const alice = await aliceContext.newPage();
    await registerFromProtectedPage(alice, base, "Account Alice", "alice-pass-123", "/collection");

    const emptyAliceDecks = await api(alice, "/api/decks?locale=zhCN");
    assert.equal(emptyAliceDecks.status, 200);
    assert.deepEqual(emptyAliceDecks.payload.decks, []);
    const saved = await api(alice, "/api/decks/save", {
      method: "POST",
      body: { name: "Alice private deck", hero_id: "HERO_08", card_ids: [], locale: "zhCN" },
    });
    assert.equal(saved.status, 200, JSON.stringify(saved.payload));
    const aliceDeckId = saved.payload.saved_id;
    assert(aliceDeckId, "saving a deck must return its owner-scoped ID");

    const aliceArenaStart = await api(alice, "/api/arena/start", {
      method: "POST",
      body: {
        nickname: "Alice",
        locale: "zhCN",
        set_ids: ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"],
      },
    });
    assert.equal(aliceArenaStart.status, 200, JSON.stringify(aliceArenaStart.payload));
    assert.equal(aliceArenaStart.payload.mode, "hero");

    const bobContext = await browser.newContext();
    const bob = await bobContext.newPage();
    await registerFromProtectedPage(bob, base, "Account Bob", "bob-pass-123", "/arena");
    await bob.locator('[data-testid="arena-stage"]').waitFor({ state: "visible", timeout });

    const bobDecks = await api(bob, "/api/decks?locale=zhCN");
    assert.equal(bobDecks.status, 200);
    assert.deepEqual(bobDecks.payload.decks, [], "another account must not see Alice's saved deck");
    const stolenDeckStart = await api(bob, "/api/start", {
      method: "POST",
      body: { nickname: "Bob", locale: "zhCN", deck_id: aliceDeckId },
    });
    assert.equal(stolenDeckStart.status, 400, "another account must not start a private deck");

    const bobArena = await api(bob, "/api/arena/state?locale=zhCN");
    assert.equal(bobArena.status, 200);
    assert.equal(bobArena.payload.mode, "setup", "Arena draft progress must be account scoped");

    // Keep Alice in her Arena draft while Bob starts a separate match.
    const bobMatch = await api(bob, "/api/start", {
      method: "POST",
      body: { nickname: "Bob", locale: "zhCN" },
    });
    assert.equal(bobMatch.status, 200, JSON.stringify(bobMatch.payload));
    assert.equal(bobMatch.payload.mode, "match");
    const aliceArenaAgain = await api(alice, "/api/arena/state?locale=zhCN");
    assert.equal(aliceArenaAgain.payload.mode, "hero");
    assert.equal(aliceArenaAgain.payload.run_id, aliceArenaStart.payload.run_id);

    const unauthContext = await browser.newContext();
    const unauthPage = await unauthContext.newPage();
    await unauthPage.goto(new URL("/", base).toString(), { waitUntil: "domcontentloaded" });
    await unauthPage.waitForURL((url) => new URL(url).pathname === "/account", { timeout });
    const privateApi = await api(unauthPage, "/api/decks?locale=zhCN");
    assert.equal(privateApi.status, 401, "private APIs must reject requests without a session");
    await unauthContext.close();

    const aliceOtherTab = await aliceContext.newPage();
    await aliceOtherTab.goto(new URL("/collection", base).toString(), { waitUntil: "domcontentloaded" });
    await aliceOtherTab.locator('[data-testid="account-toolbar"]').waitFor({ state: "visible", timeout });
    await alice.locator("#collection-account-logout").click();
    await alice.waitForURL((url) => new URL(url).pathname === "/account", { timeout });
    await aliceOtherTab.waitForURL((url) => new URL(url).pathname === "/account", { timeout });
    assert.equal(await aliceOtherTab.locator('[data-testid="collection-layout"]').count(), 0,
      "another tab must clear its previous account's private deck view");
    const aliceAfterLogout = await api(alice, "/api/account/session");
    assert.equal(aliceAfterLogout.payload.authenticated, false);
    assert.equal((await api(alice, "/api/decks?locale=zhCN")).status, 401);

    await alice.goto(new URL("/account?next=%2Fcollection", base).toString(), { waitUntil: "domcontentloaded" });
    await alice.locator("#account-username").fill("Account Alice");
    await alice.locator("#account-password").fill("alice-pass-123");
    await alice.locator("#account-submit").click();
    await alice.waitForURL((url) => new URL(url).pathname === "/collection", { timeout });
    const aliceAfterLogin = await api(alice, "/api/decks?locale=zhCN");
    assert.equal(aliceAfterLogin.status, 200);
    assert.equal(aliceAfterLogin.payload.decks[0].id, aliceDeckId, "logging back in must restore the same account data");
    const restoredArena = await api(alice, "/api/arena/state?locale=zhCN");
    assert.equal(restoredArena.payload.run_id, aliceArenaStart.payload.run_id);

    const aliceSession = await api(alice, "/api/account/session");
    const accountInfoTab = await aliceContext.newPage();
    await accountInfoTab.goto(new URL("/account", base).toString(), { waitUntil: "domcontentloaded" });
    await accountInfoTab.locator("#account-session-username").getByText("Account Alice").waitFor({ timeout });
    await alice.evaluate((accountId) => {
      localStorage.setItem(`fireplace.nickname.${accountId}`, "Alice private nickname");
    }, aliceSession.payload.account.id);
    await alice.locator("#collection-account-logout").click();
    await alice.waitForURL((url) => new URL(url).pathname === "/account", { timeout });
    await alice.locator("#account-username").fill("Account Bob");
    await alice.locator("#account-password").fill("bob-pass-123");
    await alice.locator("#account-submit").click();
    await alice.waitForURL((url) => new URL(url).pathname === "/", { timeout });
    await alice.locator("#nickname-input").waitFor({ state: "attached", timeout });
    await accountInfoTab.locator("#account-session-username").getByText("Account Bob").waitFor({ timeout });
    assert.equal(await alice.locator("#nickname-input").inputValue(), "Account Bob",
      "a different account on the same browser must not inherit Alice's nickname");

    console.log("account browser acceptance passed: registration, protected routes, public catalog, deck and Arena isolation, concurrent per-account game state");
    await aliceOtherTab.close();
    await accountInfoTab.close();
    await bobContext.close();
    await aliceContext.close();
  } finally {
    if (browser) await browser.close();
    if (server.child.exitCode === null && server.child.signalCode === null) {
      server.child.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => server.child.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 5000)),
      ]);
      if (server.child.exitCode === null && server.child.signalCode === null) server.child.kill("SIGKILL");
    }
    fs.rmSync(dataRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
