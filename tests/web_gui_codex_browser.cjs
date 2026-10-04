#!/usr/bin/env node
/* Browser acceptance for the asynchronous Codex opponent contract. */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_codex_browser_fixture.py");
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
        // Engine diagnostics may precede the readiness JSON.
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

async function main() {
  const server = startFixture();
  let browser;
  try {
    const fixtureInfo = await server.ready;
    browser = await chromium.launch({ headless: true, executablePath: chrome, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    await context.addInitScript(() => {
      const originalAnimate = Element.prototype.animate;
      window.__presentationAnimations = 0;
      Element.prototype.animate = function (...args) {
        window.__presentationAnimations += 1;
        return originalAnimate.apply(this, args);
      };
    });
    await context.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, account: { id: "codex-fixture", username: "Codex fixture" }, legacy_available: false }),
    }));
    await context.route("**/api/decks*", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ decks: [] }),
    }));
    await context.route("**/assets/**", (route) => route.fulfill({ status: 404, body: "" }));

    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const states = [];
    page.on("pageerror", (error) => states.push(`pageerror: ${error.stack || error}`));
    page.on("requestfailed", (request) => {
      if (!new URL(request.url()).pathname.startsWith("/assets/")) {
        states.push(`requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
      }
    });
    await page.goto(fixtureInfo.url, { waitUntil: "domcontentloaded" });
    await page.locator("#action-submit").waitFor({ state: "visible" });
    assert.equal(await page.locator("#opponent-select option").count(), 3);

    // Opening Mulligan action starts the real fixture's first delayed Codex call.
    const initialAction = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/action");
    await page.locator("#action-submit").click();
    let initialResponse;
    try {
      initialResponse = await initialAction;
    } catch (error) {
      throw new Error(`${error.message}; diagnostics=${JSON.stringify(states)}`);
    }
    const initial = await initialResponse.json();
    assert.equal(initialResponse.status(), 200, JSON.stringify(initial));
    assert.equal(initial.llm.state, "thinking");
    assert.equal(await page.locator("#action-instructions").innerText(), "等待对手完成操作……");
    await page.locator("#llm-status.error").waitFor({ state: "visible" });
    assert.match(await page.locator("#llm-status-message").innerText(), /Codex/);
    assert.equal(await page.locator("#llm-retry").isVisible(), true);
    assert.equal(await page.locator("#end-turn-button").isVisible(), false,
      "humans must not receive a playable action while Codex is thinking or failed");

    const retryRequest = page.waitForRequest((request) =>
      request.method() === "POST" && new URL(request.url()).pathname === "/api/opponent/retry");
    const retryResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/opponent/retry");
    await page.locator("#llm-retry").click();
    const [retryBody, retryResult] = await Promise.all([retryRequest, retryResponse]);
    assert.deepEqual(retryBody.postDataJSON(), {
      session_id: initial.session_id,
      revision: initial.revision,
    });
    const retrySnapshot = await retryResult.json();
    assert.equal(retryResult.status(), 200, JSON.stringify(retrySnapshot));
    assert.equal(retrySnapshot.llm.state, "thinking");
    await page.locator("#llm-status.thinking").waitFor({ state: "visible" });

    // The bounded GET step window carries three delayed AI actions. Their
    // revisions must converge through the existing presentation queue.
    await page.locator("#end-turn-button").waitFor({ state: "visible", timeout: timeout * 2 });
    await page.waitForFunction(() => Number(document.querySelector("#revision-value")?.textContent?.match(/\d+/)?.[0] || 0) >= 4);
    await page.waitForFunction(() => window.fireplaceWebGui && !window.fireplaceWebGui.isBusy());
    assert(await page.evaluate(() => window.__presentationAnimations) >= 3,
      "multiple AI presentation frames should animate through the browser queue");

    const beforeHuman = await page.evaluate(async () => (await fetch("/api/state", { cache: "no-store" })).json());
    assert(beforeHuman.legal_actions.length > 0, "the fixture must return control to the human");
    assert.equal(await page.locator("#end-turn-button").isVisible(), true);
    const humanAction = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/action");
    await page.locator("#end-turn-button").click();
    const humanResponse = await humanAction;
    const humanSnapshot = await humanResponse.json();
    assert.equal(humanResponse.status(), 200, JSON.stringify(humanSnapshot));
    await page.waitForFunction(() => window.fireplaceWebGui && !window.fireplaceWebGui.isBusy());
    await page.locator("#llm-status.thinking").waitFor({ state: "visible" });

    // Concession remains available while the asynchronous Codex call is in
    // flight and invalidates the delayed worker at the real WebGame boundary.
    await page.keyboard.press("Escape");
    await page.locator("#surrender-menu").waitFor({ state: "visible" });
    const concedeRequest = page.waitForRequest((request) =>
      request.method() === "POST" && new URL(request.url()).pathname === "/api/concede");
    const concedeResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/concede");
    const staleConcedeRetry = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/concede" &&
      response.request().postDataJSON()?.revision > humanSnapshot.revision);
    await page.locator("#surrender-confirm").click();
    const [concedeBody, terminalResponse] = await Promise.all([concedeRequest, concedeResponse]);
    assert.equal(concedeBody.postDataJSON().session_id, humanSnapshot.session_id);
    let terminal = await terminalResponse.json();
    if (terminalResponse.status() === 409) {
      // The Codex worker can commit one more revision between the first
      // request and the server's stale-revision response. The UI retries once
      // against that authoritative response, preserving surrender intent.
      const retryResponse = await staleConcedeRetry;
      terminal = await retryResponse.json();
      assert.equal(retryResponse.status(), 200, `${JSON.stringify(terminal)} diagnostics=${JSON.stringify(states)}`);
    }
    assert.equal(terminal.observation.phase, "GAME_OVER", JSON.stringify(terminal));
    assert(terminal.outcome);
    assert.equal(await page.locator("#llm-status").isHidden(), true);
    assert.equal(states.length, 0, states.join("\n"));
    console.log(JSON.stringify({ result: "PASS", animations: await page.evaluate(() => window.__presentationAnimations) }));
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
