#!/usr/bin/env node
/* Browser acceptance for the Codex-vs-Codex spectator controls. */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_codex_codex_browser_fixture.py");
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
      } catch (_error) {
        // Engine diagnostics may precede readiness JSON.
      }
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

async function readState(page) {
  return page.evaluate(async () => (await fetch("/api/state", { cache: "no-store" })).json());
}

async function waitForState(page, predicate, description) {
  const deadline = Date.now() + timeout;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await readState(page);
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 70));
  }
  throw new Error(`timed out waiting for ${description}: ${JSON.stringify(latest)}`);
}

async function clickAutomation(page, id) {
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/automation"
  );
  await page.locator(`#${id}`).click();
  return responsePromise;
}

async function main() {
  const server = startFixture();
  let browser;
  try {
    const fixtureInfo = await server.ready;
    browser = await chromium.launch({ headless: true, executablePath: chrome, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    await context.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, account: { id: "duel-fixture", username: "Codex duel fixture" }, legacy_available: false }),
    }));
    await context.route("**/api/decks*", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ decks: [] }),
    }));
    await context.route("**/assets/**", (route) => route.fulfill({ status: 404, body: "" }));

    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.stack || String(error)));
    page.on("requestfailed", (request) => {
      if (!new URL(request.url()).pathname.startsWith("/assets/")) {
        errors.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
      }
    });
    await page.goto(fixtureInfo.url, { waitUntil: "domcontentloaded" });
    await page.locator("#automation-status").waitFor({ state: "visible" });

    const controllers = await page.locator("#automation-controllers").innerText();
    assert.match(controllers, /Codex · fixture-seat0/);
    assert.match(controllers, /Codex · fixture-seat1/);
    assert.doesNotMatch(controllers, /MCTS/);
    assert.match(await page.locator("#automation-mode-label").innerText(), /Codex vs Codex/);
    assert.equal(await page.locator("#automation-state-label").innerText(), "观战已暂停");
    assert.equal(await page.locator("#automation-step").isEnabled(), true);
    assert.equal(await page.locator("#end-turn-button").isVisible(), false);
    assert.equal(await page.locator("#action-submit").isVisible(), false);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#surrender-menu").isHidden(), true,
      "spectator mode must not expose human surrender controls");

    let state = await readState(page);
    assert.deepEqual(state.automation.controllers, [
      { kind: "codex", model: "fixture-seat0" },
      { kind: "codex", model: "fixture-seat1" },
    ]);
    assert.equal(state.automation.current_seat, 0);

    // Step one action for each independent seat.  The engine keeps seat 1
    // active after its mulligan, which lets the scripted second call fail at
    // the same revision and exercises the retry CAS.
    let response = await clickAutomation(page, "automation-step");
    let body = await response.json();
    assert.equal(response.status(), 200, JSON.stringify(body));
    state = await waitForState(page, (value) => value.revision === 1 &&
      value.automation?.paused === true && value.automation?.pending !== true &&
      value.automation?.current_seat === 1, "seat 0 step");
    assert.equal(state.llm?.state, "idle");

    response = await clickAutomation(page, "automation-step");
    body = await response.json();
    assert.equal(response.status(), 200, JSON.stringify(body));
    state = await waitForState(page, (value) => value.revision === 2 &&
      value.automation?.paused === true && value.automation?.pending !== true &&
      value.automation?.current_seat === 1, "seat 1 step");

    // The second seat's next decision is scripted to fail.  The public error
    // must identify seat one and retain the revision for an idempotent retry.
    response = await clickAutomation(page, "automation-step");
    body = await response.json();
    assert.equal(response.status(), 200, JSON.stringify(body));
    state = await waitForState(page, (value) => value.revision === 2 &&
      value.llm?.state === "error" && value.llm?.seat === 1 &&
      value.automation?.error_seat === 1 && value.automation?.paused === true,
    "seat 1 error");
    assert.match(await page.locator("#llm-status-label").innerText(), /席位 2/);
    await page.locator("#llm-retry").waitFor({ state: "visible" });
    assert.equal(await page.locator("#llm-retry").isEnabled(), true);
    assert.doesNotMatch(await page.locator("#llm-status-message").innerText(), /fixture seat 1 failure/);

    const retryResponsePromise = page.waitForResponse((value) =>
      value.request().method() === "POST" && new URL(value.url()).pathname === "/api/opponent/retry"
    );
    await page.locator("#llm-retry").click();
    const retryResponse = await retryResponsePromise;
    const retried = await retryResponse.json();
    assert.equal(retryResponse.status(), 200, JSON.stringify(retried));
    assert.equal(retried.llm?.seat, 1);
    assert.equal(retried.llm?.state, "thinking");
    await page.locator("#llm-status").waitFor({ state: "visible" });

    // Pause the replacement while it is thinking.  The fake records and
    // validates its observation before its delay, so this both proves retry
    // replaced seat 1 and keeps the test at the same revision for the CAS.
    await page.locator("#automation-pause").waitFor({ state: "visible" });
    await page.waitForTimeout(120);
    await page.locator("#automation-pause").waitFor({ state: "attached" });
    if (await page.locator("#automation-pause").isEnabled()) {
      response = await clickAutomation(page, "automation-pause");
      body = await response.json();
      assert.equal(response.status(), 200, JSON.stringify(body));
      assert.equal(body.automation.paused, true);
      assert.equal(body.automation.controllers[1].model, "fixture-seat1-retry");
    }
    state = await waitForState(page, (value) => value.automation?.paused === true &&
      value.automation?.pending !== true, "pause after retry");
    assert.equal(state.llm?.state, "idle");

    response = await clickAutomation(page, "automation-stop");
    body = await response.json();
    assert.equal(response.status(), 200, JSON.stringify(body));
    assert.equal(body.mode, "lobby");
    await page.locator("#lobby-screen").waitFor({ state: "visible" });
    assert.equal(await page.locator("#game").isHidden(), true);

    // The real match has ended; exercise the duel lobby controls and request
    // contract without starting a live Codex process.  The match itself above
    // remains entirely backed by the production WebGame HTTP boundary.
    await page.locator("#battle-mode-select").selectOption("codex_codex");
    await page.locator("#codex-self-model-field").waitFor({ state: "visible" });
    await page.locator("#codex-opponent-model-field").waitFor({ state: "visible" });
    assert.match(await page.locator("#codex-self-model-label").innerText(), /第一席/);
    assert.match(await page.locator("#codex-opponent-model-label").innerText(), /第二席/);
    await page.locator("#nickname-input").fill("Duel lobby");
    await page.locator("#codex-self-model-input").fill("lobby-seat0");
    await page.locator("#codex-opponent-model-input").fill("lobby-seat1");
    let startBody = null;
    await context.route("**/api/start", async (route) => {
      startBody = route.request().postDataJSON();
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ error: "fixture lobby request captured" }),
      });
    });
    await page.locator("#start-match-button").click();
    await page.waitForFunction(() => document.querySelector("#lobby-status")?.textContent.includes("fixture lobby"));
    assert.deepEqual(startBody, {
      nickname: "Duel lobby",
      locale: "zhCN",
      battle_mode: "codex_codex",
      codex_self_model: "lobby-seat0",
      codex_model: "lobby-seat1",
    });
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(JSON.stringify({ result: "PASS", errorSeat: 1, controllers }));
    await context.close();
  } finally {
    if (browser) await browser.close();
    await stopFixture(server.child);
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
