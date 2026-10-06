#!/usr/bin/env node
/* Browser acceptance for explicit, optional local Codex connection controls. */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_codex_connection_browser_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const artifacts = process.env.FIREPLACE_GUI_ARTIFACTS || "/tmp/tavernlab-codex-ui-qa";
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);

function startFixture(dataRoot) {
  const statePath = path.join(dataRoot, "fixture-state.json");
  const child = spawn(python, ["-u", fixture, "--port", "0"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      FIREPLACE_ACCOUNT_STATE: path.join(dataRoot, "accounts.sqlite3"),
      TAVERNLAB_ACCOUNT_STATE: path.join(dataRoot, "accounts.sqlite3"),
      FIREPLACE_ACCOUNT_DATA_ROOT: path.join(dataRoot, "users"),
      TAVERNLAB_ACCOUNT_DATA_ROOT: path.join(dataRoot, "users"),
      TAVERNLAB_CODEX_HOME: path.join(dataRoot, "codex-home"),
      CODEX_HOME: path.join(dataRoot, "codex-home"),
      FIREPLACE_CODEX_FIXTURE_STATE: statePath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  const lines = readline.createInterface({ input: child.stdout });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`fixture startup timed out\n${logs.join("")}`)), timeout);
    lines.on("line", (line) => {
      logs.push(`${line}\n`);
      try {
        const value = JSON.parse(line);
        if (value && typeof value.url === "string" && value.state_path === statePath) {
          clearTimeout(timer);
          resolve(value);
        }
      } catch (_error) {
        // Database and HTTP diagnostics can precede the single readiness line.
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
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

function readFixtureState(statePath) {
  return JSON.parse(fs.readFileSync(statePath, "utf8"));
}

function codexRequests(requests, { method, pathname } = {}) {
  return requests.filter((item) => item.pathname.startsWith("/api/codex/") &&
    (!method || item.method === method) && (!pathname || item.pathname === pathname));
}

async function noteFailure(failures, label, callback) {
  try {
    await callback();
  } catch (error) {
    failures.push(`${label}: ${error.message}`);
  }
}

async function apiResponse(page, pathname, method = "GET") {
  return page.waitForResponse((response) => response.request().method() === method &&
    new URL(response.url()).pathname === pathname, { timeout });
}

async function main() {
  fs.mkdirSync(artifacts, { recursive: true });
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), "tavernlab-codex-browser-"));
  const server = startFixture(dataRoot);
  let browser;
  let context;
  const failures = [];
  try {
    const fixtureInfo = await server.ready;
    browser = await chromium.launch({
      headless: process.env.FIREPLACE_GUI_HEADFUL !== "1",
      executablePath: chrome,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.route("https://auth.openai.com/**", (route) => route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      body: "<!doctype html><title>Mock official login</title><main>Fixture login route</main>",
    }));
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const requests = [];
    const responses = new Map();
    const diagnostics = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      requests.push({
        method: request.method(),
        pathname: url.pathname,
        body: request.method() === "GET" ? null : request.postDataJSON(),
      });
      if (url.origin !== new URL(fixtureInfo.url).origin && url.hostname !== "auth.openai.com") {
        diagnostics.push(`external request: ${request.url()}`);
      }
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.pathname === "/codex_connection.js" || url.pathname === "/style-codex-connection.css") {
        responses.set(url.pathname, { status: response.status(), contentType: response.headers()["content-type"] || "" });
      }
    });
    page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error.stack || error}`));

    // Use a disposable local account; the real Codex home is never inspected.
    await page.goto(new URL("/account", fixtureInfo.url).toString(), { waitUntil: "domcontentloaded" });
    const registration = await page.evaluate(async () => {
      const response = await fetch("/api/account/register", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username: "Codex Browser QA", password: "fixture-password-123" }),
      });
      return { status: response.status, payload: await response.json() };
    });
    assert.equal(registration.status, 200, JSON.stringify(registration.payload));
    assert.equal(registration.payload.authenticated, true);
    await page.evaluate(() => localStorage.setItem("fireplace.opponent", "radical"));
    await page.goto(fixtureInfo.url, { waitUntil: "domcontentloaded" });
    await page.locator("#lobby-setup").waitFor({ state: "visible" });
    await page.locator("#opponent-select").waitFor({ state: "visible" });
    assert.equal(await page.locator("#opponent-select").inputValue(), "mcts", "retired Radical preference falls back to MCTS");
    assert.equal(await page.locator('#opponent-select option[value="radical"]').count(), 0);
    assert.match(await page.locator('#battle-mode-select option[value="codex_mcts"]').innerText(), /^观战模式\s*\//);
    assert.match(await page.locator('#battle-mode-select option[value="codex_codex"]').innerText(), /^观战模式\s*\//);
    await page.waitForTimeout(500);

    await noteFailure(failures, "ordinary lobby must not query Codex", () => {
      assert.equal(codexRequests(requests).length, 0);
      assert.equal(readFixtureState(fixtureInfo.state_path).calls.length, 0);
    });
    await noteFailure(failures, "connection assets must be served", () => {
      assert.equal(responses.get("/codex_connection.js")?.status, 200);
      assert.match(responses.get("/codex_connection.js")?.contentType || "", /javascript/);
      assert.equal(responses.get("/style-codex-connection.css")?.status, 200);
      assert.match(responses.get("/style-codex-connection.css")?.contentType || "", /text\/css/);
    });
    await noteFailure(failures, "ordinary lobby must not start a child", () => {
      assert.equal(readFixtureState(fixtureInfo.state_path).child_start_attempts, 0);
    });

    // The ordinary MCTS lobby remains offline because Codex is not selected.
    await page.locator("#opponent-select").selectOption("mcts");
    await page.waitForTimeout(350);
    await noteFailure(failures, "MCTS lobby must not query or start Codex", () => {
      assert.equal(codexRequests(requests).length, 0);
      assert.equal(readFixtureState(fixtureInfo.state_path).child_start_attempts, 0);
    });

    // Selecting a Codex opponent makes the panel visible and reads its cached
    // status. The missing CLI state should show the official install link.
    const initialStatusPromise = apiResponse(page, "/api/codex/status");
    await page.locator("#opponent-select").selectOption("codex");
    await page.locator("#codex-connection-panel").waitFor({ state: "visible" });
    await initialStatusPromise;
    await page.locator("#codex-connection-status").waitFor({ state: "visible" });
    await noteFailure(failures, "missing CLI state must expose official install guidance", async () => {
      assert.equal(new URL(await page.locator("#codex-connection-docs-link").getAttribute("href")).origin, "https://learn.chatgpt.com");
      assert.equal(await page.locator("#codex-connection-missing").isVisible(), true);
    });

    const checkResponsePromise = apiResponse(page, "/api/codex/check", "POST");
    await page.locator("#codex-check-button").click();
    const checkResponse = await checkResponsePromise;
    assert.equal(checkResponse.status(), 200);
    await page.locator("#codex-connect-button").waitFor({ state: "visible" });

    await page.locator("#codex-connection-advanced summary").click();
    await page.locator("#codex-proxy-url").fill("http://user:secret@proxy.invalid");
    const beforeInvalidSettings = codexRequests(requests, { method: "POST", pathname: "/api/codex/settings" }).length;
    await page.locator("#codex-settings-button").click();
    await page.locator("#codex-connection-error[role=alert]").waitFor({ state: "visible" });
    const afterInvalidSettings = codexRequests(requests, { method: "POST", pathname: "/api/codex/settings" }).length;
    await noteFailure(failures, "invalid proxy should show an accessible Chinese error without saving", async () => {
      assert.match(await page.locator("#codex-connection-error").innerText(), /代理必须/);
      assert.equal(afterInvalidSettings, beforeInvalidSettings);
      assert.equal(await page.locator("#codex-connection-error").getAttribute("role"), "alert");
    });
    await page.locator("#codex-proxy-url").fill("http://127.0.0.1:7890");
    const settingsResponsePromise = apiResponse(page, "/api/codex/settings", "POST");
    await page.locator("#codex-settings-button").click();
    const settingsResponse = await settingsResponsePromise;
    assert.equal(settingsResponse.status(), 200);
    const settingsBody = codexRequests(requests, { method: "POST", pathname: "/api/codex/settings" }).at(-1)?.body;
    assert.deepEqual(settingsBody, { binary_path: "", proxy_url: "http://127.0.0.1:7890" });

    // Login opens only a mocked official auth origin. While pending, hiding the
    // panel must stop the browser's status polling until the panel is selected.
    const loginPopupPromise = context.waitForEvent("page");
    const loginResponsePromise = apiResponse(page, "/api/codex/login", "POST");
    await page.locator("#codex-connect-button").click();
    const [loginResponse, loginPopup] = await Promise.all([loginResponsePromise, loginPopupPromise]);
    assert.equal(loginResponse.status(), 200);
    await loginPopup.waitForURL((url) => url.hostname === "auth.openai.com");
    await loginPopup.locator("main").waitFor({ state: "visible" });
    assert.equal(await page.locator("#codex-cancel-button").isVisible(), true);
    const pendingPollResponse = await apiResponse(page, "/api/codex/status");
    assert.equal(pendingPollResponse.status(), 200, "pending login should poll Codex status while visible");
    const statusCountBeforeHide = codexRequests(requests, { pathname: "/api/codex/status" }).length;
    await page.locator("#opponent-select").selectOption("mcts");
    await page.locator("#codex-connection-panel").waitFor({ state: "hidden" });
    await page.waitForTimeout(2800);
    await noteFailure(failures, "hidden pending panel must stop status polling", () => {
      assert.equal(codexRequests(requests, { pathname: "/api/codex/status" }).length, statusCountBeforeHide);
      assert.equal(readFixtureState(fixtureInfo.state_path).child_start_attempts, 0);
    });

    const resumedStatusPromise = apiResponse(page, "/api/codex/status");
    await page.locator("#opponent-select").selectOption("codex");
    await resumedStatusPromise;
    const cancelResponsePromise = apiResponse(page, "/api/codex/cancel", "POST");
    await page.locator("#codex-cancel-button").click();
    const cancelResponse = await cancelResponsePromise;
    assert.equal(cancelResponse.status(), 200);
    await page.locator("#codex-cancel-button").waitFor({ state: "hidden" });

    // The fixture's second login completes locally, letting the test exercise
    // model selection, connection errors, translated live regions, and logout.
    const secondLoginPopupPromise = context.waitForEvent("page");
    const secondLoginResponsePromise = apiResponse(page, "/api/codex/login", "POST");
    await page.locator("#codex-connect-button").click();
    const [secondLoginResponse, secondLoginPopup] = await Promise.all([secondLoginResponsePromise, secondLoginPopupPromise]);
    assert.equal(secondLoginResponse.status(), 200);
    await secondLoginPopup.waitForURL((url) => url.hostname === "auth.openai.com");
    await page.locator("#codex-connection-account").waitFor({ state: "visible" });
    await page.locator("#codex-connection-account-email").waitFor({ state: "visible" });
    assert.equal(await page.locator("#codex-connection-account-email").innerText(), "browser-fixture@example.invalid");
    assert.equal(await page.locator("#codex-logout-button").innerText(), "退出本机 CLI 账号");
    assert.match(await page.locator("#codex-connection-description").innerText(), /会使本机 CLI 退出登录/);

    await page.locator("#codex-model-input").fill("browser-fixture-model");
    const testResponsePromise = apiResponse(page, "/api/codex/test", "POST");
    await page.locator("#codex-test-button").click();
    const testResponse = await testResponsePromise;
    assert.equal(testResponse.status(), 200);
    assert.deepEqual(codexRequests(requests, { method: "POST", pathname: "/api/codex/test" }).at(-1)?.body, { model: "browser-fixture-model" });

    await page.screenshot({ path: path.join(artifacts, "codex-connection-selected.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(artifacts, "codex-connection-selected-390px.png"), fullPage: true });
    const narrowLayout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      panel: document.querySelector("#codex-connection-panel").getBoundingClientRect().toJSON(),
      body: document.body.getBoundingClientRect().toJSON(),
    }));
    await noteFailure(failures, "selected Codex panel should fit a 390px viewport", () => {
      assert(narrowLayout.document <= narrowLayout.viewport, JSON.stringify(narrowLayout));
      assert(narrowLayout.panel.left >= 0 && narrowLayout.panel.right <= narrowLayout.viewport, JSON.stringify(narrowLayout));
    });
    await page.setViewportSize({ width: 1280, height: 900 });

    await page.locator("#codex-model-input").fill("force-unsuccessful");
    const unsuccessfulTestResponsePromise = apiResponse(page, "/api/codex/test", "POST");
    await page.locator("#codex-test-button").click();
    const unsuccessfulTestResponse = await unsuccessfulTestResponsePromise;
    assert.equal(unsuccessfulTestResponse.status(), 200);
    await page.locator("#codex-connection-error[role=alert]").waitFor({ state: "visible" });
    const chineseFailure = {
      status: await page.locator("#codex-connection-status").innerText(),
      alert: await page.locator("#codex-connection-error").innerText(),
    };
    await noteFailure(failures, "HTTP 200 with success=false must not announce a successful test", async () => {
      assert.match(chineseFailure.status, /未通过/);
      assert.doesNotMatch(chineseFailure.status, /成功|success/i);
      assert.match(chineseFailure.alert, /[\u3400-\u9fff]/, "the alert should be localized for Chinese users");
      assert.equal(await page.locator("#codex-connection-error").getAttribute("role"), "alert");
    });
    await page.locator("#locale-enUS").click();
    await page.waitForFunction(() => document.documentElement.lang === "en");
    assert.equal(await page.locator("#codex-logout-button").innerText(), "Log out local CLI account");
    assert.match(await page.locator("#codex-connection-description").innerText(), /logs the local CLI out/);
    await page.locator("#codex-model-input").fill("force-unsuccessful");
    const englishFailureResponsePromise = apiResponse(page, "/api/codex/test", "POST");
    await page.locator("#codex-test-button").click();
    const englishFailureResponse = await englishFailureResponsePromise;
    assert.equal(englishFailureResponse.status(), 200);
    await page.locator("#codex-connection-error[role=alert]").waitFor({ state: "visible" });
    const englishFailure = {
      status: await page.locator("#codex-connection-status").innerText(),
      alert: await page.locator("#codex-connection-error").innerText(),
    };
    await noteFailure(failures, "Codex failure should translate in the English alert", async () => {
      assert.match(englishFailure.status, /did not pass/i);
      assert.match(englishFailure.alert, /Codex connection test/i);
      assert.doesNotMatch(englishFailure.alert, /[\u3400-\u9fff]/);
    });

    const logoutResponsePromise = apiResponse(page, "/api/codex/logout", "POST");
    await page.locator("#codex-logout-button").click();
    const logoutResponse = await logoutResponsePromise;
    assert.equal(logoutResponse.status(), 200);
    const finalFixtureState = readFixtureState(fixtureInfo.state_path);
    const fixtureMethods = finalFixtureState.calls.map((call) => call.method);
    for (const method of ["status", "check", "save_settings", "start_login", "cancel_login", "test_connection", "logout"]) {
      assert(fixtureMethods.includes(method), `explicit UI action should reach fake service: ${method}`);
    }
    assert.equal(fixtureMethods.filter((method) => method === "start_login").length, 2);
    assert.equal(fixtureMethods.filter((method) => method === "test_connection").length, 3);
    assert.equal(finalFixtureState.child_start_attempts, 0);
    assert(finalFixtureState.calls.some((call) => call.method === "test_connection" && call.model === "browser-fixture-model"));
    assert.deepEqual(diagnostics, [], diagnostics.join("\n"));
    console.log(JSON.stringify({
      result: failures.length ? "FAIL" : "PASS",
      failures,
      calls: finalFixtureState.calls.map((call) => call.method),
      childStartAttempts: finalFixtureState.child_start_attempts,
      codexRequestCount: codexRequests(requests).length,
      narrowLayout,
      screenshots: [
        path.join(artifacts, "codex-connection-selected.png"),
        path.join(artifacts, "codex-connection-selected-390px.png"),
      ],
    }));
    assert.deepEqual(failures, [], failures.join("\n"));
    await context.close();
  } finally {
    if (browser) await browser.close();
    await stopFixture(server.child);
    fs.rmSync(dataRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
