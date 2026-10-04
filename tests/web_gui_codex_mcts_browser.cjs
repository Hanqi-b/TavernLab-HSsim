#!/usr/bin/env node
/* Browser acceptance for the Codex-vs-MCTS spectator controls. */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_codex_mcts_browser_fixture.py");
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
      body: JSON.stringify({ authenticated: true, account: { id: "spectator-fixture", username: "Spectator fixture" }, legacy_available: false }),
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

    assert.match(await page.locator("#automation-controllers").innerText(), /Codex/);
    assert.match(await page.locator("#automation-controllers").innerText(), /MCTS/);
    assert.match(await page.locator("#automation-state-label").innerText(), /暂停/);
    assert.equal(await page.locator("#automation-step").isEnabled(), true);
    assert.equal(await page.locator("#end-turn-button").isVisible(), false);
    assert.equal(await page.locator("#action-submit").isVisible(), false);

    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#surrender-menu").isHidden(), true,
      "spectator mode must not expose human surrender controls");

    const initial = await page.evaluate(async () => (await fetch("/api/state", { cache: "no-store" })).json());
    const stepRequest = page.waitForRequest((request) =>
      request.method() === "POST" && new URL(request.url()).pathname === "/api/automation");
    const stepResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/automation");
    await page.locator("#automation-step").click();
    const [stepBody, stepResult] = await Promise.all([stepRequest, stepResponse]);
    assert.deepEqual(stepBody.postDataJSON(), {
      command: "step",
      session_id: initial.session_id,
      revision: initial.revision,
    });
    const stepped = await stepResult.json();
    assert.equal(stepResult.status(), 200, JSON.stringify(stepped));
    let steppedState = null;
    const stepDeadline = Date.now() + timeout;
    while (Date.now() < stepDeadline) {
      steppedState = await page.evaluate(async () => (await fetch("/api/state", { cache: "no-store" })).json());
      if (steppedState.session_id === initial.session_id &&
          steppedState.revision === initial.revision + 1 &&
          steppedState.automation && steppedState.automation.paused === true &&
          steppedState.automation.pending !== true) break;
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    assert.equal(steppedState.revision, initial.revision + 1,
      "one paused step must execute exactly one engine action");
    assert.equal(steppedState.automation.paused, true);
    await page.waitForFunction(() => document.querySelector("#automation-state-label")?.textContent.includes("暂停"));
    assert.equal(await page.locator("#automation-step").isEnabled(), true);

    const resumeResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/automation");
    await page.locator("#automation-resume").click();
    const resumed = await (await resumeResponse).json();
    assert.equal(resumed.automation.paused, false);
    await page.locator("#automation-pause").waitFor({ state: "visible" });
    assert.equal(await page.locator("#automation-pause").isEnabled(), true);

    const pauseResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/automation");
    await page.locator("#automation-pause").click();
    const paused = await (await pauseResponse).json();
    assert.equal(paused.automation.paused, true);
    await page.locator("#automation-state-label").waitFor({ state: "visible" });
    assert.match(await page.locator("#automation-state-label").innerText(), /暂停/);

    const beforeStop = await page.evaluate(async () => (await fetch("/api/state", { cache: "no-store" })).json());
    const stopResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/automation");
    await page.locator("#automation-stop").click();
    const stopped = await (await stopResponse).json();
    assert.equal(stopped.mode, "lobby");
    assert.equal(await page.locator("#lobby-screen").isVisible(), true);
    assert.equal(await page.locator("#game").isHidden(), true);
    assert(beforeStop.revision >= initial.revision + 1);
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(JSON.stringify({ result: "PASS", stepRevision: steppedState.revision }));
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
