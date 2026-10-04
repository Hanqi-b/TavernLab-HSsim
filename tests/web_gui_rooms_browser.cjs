#!/usr/bin/env node
/* Browser acceptance for authenticated human-vs-human rooms. */

"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_rooms_browser_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || path.join(root, "venv/bin/python");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
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
    const timer = setTimeout(() => reject(new Error(`fixture startup timed out\n${logs.join("")}`)), timeout);
    readline.createInterface({ input: child.stdout }).on("line", (line) => {
      logs.push(`${line}\n`);
      try {
        const value = JSON.parse(line);
        if (value && typeof value.url === "string") {
          clearTimeout(timer);
          resolve(value);
        }
      } catch (_error) { /* initialization logs precede readiness JSON */ }
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

async function stopFixture(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
  });
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
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

async function register(page, base, username, password) {
  await page.goto(new URL("/account?next=%2F", base).toString(), { waitUntil: "domcontentloaded" });
  await page.locator("#register-tab").click();
  await page.locator("#account-username").fill(username);
  await page.locator("#account-password").fill(password);
  await page.locator("#account-confirm-password").fill(password);
  await page.locator("#account-submit").click();
  await page.waitForURL((url) => new URL(url).pathname === "/", { timeout });
  await page.locator("#nickname-input").waitFor({ state: "attached", timeout });
}

async function waitForState(page, predicate, description) {
  const deadline = Date.now() + timeout;
  let latest = null;
  while (Date.now() < deadline) {
    latest = (await api(page, "/api/state")).payload;
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`timed out waiting for ${description}: ${JSON.stringify(latest)}`);
}

async function chooseRoomMode(page, nickname) {
  await page.locator("#nickname-input").fill(nickname);
  await page.locator("#battle-mode-select").selectOption("human_human");
  await page.locator("#room-controls").waitFor({ state: "visible", timeout });
}

async function main() {
  const server = startFixture();
  let browser;
  try {
    const fixtureInfo = await server.ready;
    const base = fixtureInfo.url;
    browser = await chromium.launch({
      headless: process.env.FIREPLACE_GUI_HEADFUL !== "1",
      executablePath: chrome,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    const aliceContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const bobContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const thirdContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    for (const context of [aliceContext, bobContext, thirdContext]) {
      await context.route("**/assets/**", (route) => route.fulfill({ status: 404, body: "" }));
    }
    const alice = await aliceContext.newPage();
    const bob = await bobContext.newPage();
    const third = await thirdContext.newPage();
    const errors = [];
    const personalStartRequests = [];
    for (const page of [alice, bob, third]) {
      page.setDefaultTimeout(timeout);
      page.on("pageerror", (error) => errors.push(error.stack || String(error)));
      page.on("request", (request) => {
        if (new URL(request.url()).pathname === "/api/start") personalStartRequests.push(request.url());
      });
      page.on("requestfailed", (request) => {
        if (!new URL(request.url()).pathname.startsWith("/assets/")) {
          errors.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
        }
      });
    }

    await register(alice, base, "Room Alice", "alice-room-pass-123");
    await chooseRoomMode(alice, "Alice");
    const createResponsePromise = alice.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/rooms/create"
    );
    await alice.locator("#room-create-button").click();
    const createResponse = await createResponsePromise;
    const created = await createResponse.json();
    assert.equal(createResponse.status(), 200, JSON.stringify(created));
    await alice.locator("#room-waiting-panel").waitFor({ state: "visible" });
    const inviteCode = await alice.locator("#room-invite-code").inputValue();
    assert.match(inviteCode, /^[A-Za-z0-9_-]{4,32}$/);
    const storedInvite = await alice.evaluate(() => Object.keys(localStorage)
      .filter((key) => key.startsWith("fireplace.roomInvite."))
      .map((key) => localStorage.getItem(key)));
    assert(storedInvite.includes(inviteCode), "creator invite code should survive a refresh");
    assert.equal((await api(alice, "/api/rooms/current")).status, 200);
    await alice.reload({ waitUntil: "domcontentloaded" });
    await alice.locator("#room-waiting-panel").waitFor({ state: "visible", timeout });
    assert.equal(await alice.locator("#room-invite-code").inputValue(), inviteCode,
      "refresh should restore the creator's waiting room and invite code");

    await register(bob, base, "Room Bob", "bob-room-pass-123");
    await chooseRoomMode(bob, "Bob");
    await bob.locator("#room-code-input").fill(inviteCode);
    const joinResponsePromise = bob.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/rooms/join"
    );
    await bob.locator("#room-join-button").click();
    const joinResponse = await joinResponsePromise;
    const joined = await joinResponse.json();
    assert.equal(joinResponse.status(), 200, JSON.stringify(joined));
    await alice.locator("#game").waitFor({ state: "visible", timeout });
    await bob.locator("#game").waitFor({ state: "visible", timeout });
    assert.equal(await alice.locator("#room-waiting-panel").isHidden(), true);
    assert.equal(await bob.locator("#room-waiting-panel").isHidden(), true);
    assert.match(await alice.locator("#room-match-status").innerText(), /Alice|席位|Seat/);
    assert.match(await bob.locator("#room-match-status").innerText(), /Bob|席位|Seat/);

    let aliceState = await waitForState(alice, (value) => value.mode === "match" && value.room?.seat === 0, "Alice room match");
    let bobState = await waitForState(bob, (value) => value.mode === "match" && value.room?.seat === 1, "Bob room match");
    assert(aliceState.observation.self.hand.length > 0, "Alice should receive her private hand");
    assert(bobState.observation.self.hand.length > 0, "Bob should receive his private hand");
    assert.equal("hand" in aliceState.observation.opponent, false, "Alice must not receive Bob's hand");
    assert.equal("hand" in bobState.observation.opponent, false, "Bob must not receive Alice's hand");
    assert.equal(await alice.evaluate(() => Object.keys(localStorage)
      .some((key) => key.startsWith("fireplace.roomInvite."))), false,
    "joining should clear the creator invite from the browser");

    const mulligan = aliceState.legal_actions.find((action) => action.type === "MULLIGAN");
    assert(mulligan, "Alice should have a deterministic mulligan action");
    const actionResponse = await api(alice, "/api/action", {
      method: "POST",
      body: { session_id: aliceState.session_id, revision: aliceState.revision, action: mulligan },
    });
    assert.equal(actionResponse.status, 200, JSON.stringify(actionResponse.payload));
    assert(Array.isArray(actionResponse.payload.presentation_steps), "action should expose presentation frames");
    const nextRevision = actionResponse.payload.revision;
    bobState = await waitForState(bob, (value) => value.revision >= nextRevision, "Bob's propagated room action");
    assert(bobState.presentation_steps.some((frame) => frame.revision === nextRevision),
      "Bob should receive the bounded action presentation frame");
    await bob.waitForFunction((revision) => document.querySelector("#revision-value")?.textContent.includes(String(revision)), nextRevision);

    await bob.reload({ waitUntil: "domcontentloaded" });
    await bob.locator("#game").waitFor({ state: "visible", timeout });
    assert.match(await bob.locator("#room-match-status").innerText(), /Bob|Seat|席位/);
    bobState = await waitForState(bob, (value) => value.mode === "match" && value.room?.seat === 1, "Bob refresh reconnect");
    assert.equal(bobState.room.participants.length, 2);

    await register(third, base, "Room Third", "third-room-pass-123");
    await chooseRoomMode(third, "Third");
    await third.locator("#room-code-input").fill(inviteCode);
    const fullResponsePromise = third.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/rooms/join"
    );
    await third.locator("#room-join-button").click();
    const fullResponse = await fullResponsePromise;
    const fullPayload = await fullResponse.json();
    assert.notEqual(fullResponse.status(), 200, "a third account must not join a full room");
    assert.equal(typeof fullPayload.error, "string", "full-room rejection should be surfaced as safe text");
    const blockedAction = await api(third, "/api/action", {
      method: "POST",
      body: { session_id: aliceState.session_id, revision: aliceState.revision, action: mulligan },
    });
    assert.notEqual(blockedAction.status, 200, "a third account must not change the room match");

    await alice.keyboard.press("Escape");
    await alice.locator("#surrender-menu").waitFor({ state: "visible" });
    const concedeResponsePromise = alice.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/concede"
    );
    await alice.locator("#surrender-confirm").click();
    const concedeResponse = await concedeResponsePromise;
    assert.equal(concedeResponse.status(), 200);
    aliceState = await waitForState(alice, (value) => value.outcome !== null, "Alice terminal room state");
    bobState = await waitForState(bob, (value) => value.outcome !== null, "Bob terminal room state");
    assert.notEqual(aliceState.outcome.human_won, bobState.outcome.human_won);
    await alice.locator("#game-over-message").waitFor({ state: "visible" });
    await bob.locator("#game-over-message").waitFor({ state: "visible" });
    assert.notEqual(await alice.locator("#game-over-message").innerText(),
      await bob.locator("#game-over-message").innerText(), "terminal copy should reflect each player's result");

    await alice.locator("#game-over-return").click();
    await alice.locator("#lobby-screen").waitFor({ state: "visible" });
    assert.equal((await api(alice, "/api/rooms/current")).payload.room, null);
    await bob.locator("#game-over-return").click();
    await bob.locator("#lobby-screen").waitFor({ state: "visible" });
    assert.equal((await api(bob, "/api/rooms/current")).payload.room, null);

    assert.equal(personalStartRequests.length, 0, "room flows must not call /api/start");
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(JSON.stringify({ result: "PASS", inviteCodeLength: inviteCode.length, revision: nextRevision, fullRoomStatus: fullResponse.status() }));
    await thirdContext.close();
    await bobContext.close();
    await aliceContext.close();
  } finally {
    if (browser) await browser.close();
    await stopFixture(server.child);
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
