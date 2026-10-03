#!/usr/bin/env node
/* Browser coverage for the standalone match history page. */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const webRoot = path.join(root, "fireplace", "web_gui");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";

const ids = {
  normal: "10000000-0000-4000-8000-000000000001",
  arena: "10000000-0000-4000-8000-000000000002",
  broken: "10000000-0000-4000-8000-000000000003",
  complete: "10000000-0000-4000-8000-000000000004",
};

function summary(gameId, fields = {}) {
  return {
    game_id: gameId,
    revision: 4,
    mode: "normal",
    status: "in_progress",
    started_at: "2026-10-03T12:00:00Z",
    finished_at: null,
    turn: 2,
    action_count: 5,
    human_name: "History tester",
    opponent_name: "Radical",
    human_hero: "HERO_08",
    opponent_hero: "HERO_01",
    human_won: null,
    resumable: true,
    downloadable: false,
    ...fields,
  };
}

function json(response, status, body, headers = {}) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
    ...headers,
  });
  response.end(payload);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      try { resolve(body ? JSON.parse(body) : {}); } catch (error) { reject(error); }
    });
    request.on("error", reject);
  });
}

function startFixture() {
  const matches = [
    summary(ids.normal),
    summary(ids.arena, {
      mode: "arena", human_name: "Arena tester", opponent_name: "MCTS",
      human_hero: "HERO_04", opponent_hero: "HERO_01",
    }),
    summary(ids.broken, { action_count: 3 }),
    summary(ids.complete, {
      status: "complete", finished_at: "2026-10-03T12:05:00Z",
      human_won: true, resumable: false, downloadable: true,
    }),
  ];
  const requests = [];
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    requests.push({ method: request.method, pathname: url.pathname, search: url.search });

    if (url.pathname === "/api/account/session") {
      return json(response, 200, {
        authenticated: true,
        account: { id: "fixture-account", username: "History tester" },
      });
    }
    if (url.pathname === "/api/matches" && request.method === "GET") {
      const offset = Number(url.searchParams.get("offset") || 0);
      const limit = Number(url.searchParams.get("limit") || 20);
      return json(response, 200, {
        matches: matches.slice(offset, offset + limit), offset, limit, total: matches.length,
      });
    }
    if (url.pathname === "/api/matches/detail" && request.method === "GET") {
      const gameId = url.searchParams.get("game_id");
      const match = matches.find((value) => value.game_id === gameId);
      if (!match) return json(response, 404, { error: "unknown match" });
      return json(response, 200, {
        match,
        events: [
          { seq: 1, turn: 1, type: "MULLIGAN", actor: "self" },
          { seq: 2, turn: 1, type: "PLAY_CARD", actor: "opponent", source_name: "Public minion" },
        ],
      });
    }
    if (url.pathname === "/api/matches/resume" && request.method === "POST") {
      const body = await readBody(request);
      if (body.game_id === ids.broken) {
        return json(response, 409, { error: "archive signature mismatch" });
      }
      if (body.game_id !== ids.normal || body.revision !== 4) {
        return json(response, 409, { error: "stale match archive" });
      }
      return json(response, 200, { state: { mode: "match" }, match_url: "/" });
    }
    if (url.pathname === "/api/matches/abandon" && request.method === "POST") {
      const body = await readBody(request);
      const match = matches.find((value) => value.game_id === body.game_id);
      if (!match || match.revision !== body.revision || match.status !== "in_progress") {
        return json(response, 409, { error: "stale match archive" });
      }
      Object.assign(match, { status: "abandoned", resumable: false, downloadable: true, human_won: false });
      return json(response, 200, { match });
    }
    if (url.pathname === "/api/matches/download" && request.method === "GET") {
      const gameId = url.searchParams.get("game_id");
      const match = matches.find((value) => value.game_id === gameId);
      if (!match || match.status === "in_progress") return json(response, 409, { error: "match is unfinished" });
      return json(response, 200, {
        game_id: gameId,
        status: match.status,
        actions: [{ seq: 1, action: { type: "MULLIGAN" } }],
      }, { "Content-Disposition": `attachment; filename="match-${gameId}.json"` });
    }
    if (url.pathname === "/") {
      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      response.end("<!doctype html><main id=fixture-resumed>Resumed match fixture</main>");
      return;
    }

    const relative = url.pathname === "/history" ? "history.html" : url.pathname.replace(/^\//, "");
    const target = path.resolve(webRoot, relative);
    if (!target.startsWith(webRoot + path.sep) && target !== path.join(webRoot, "history.html")) {
      response.writeHead(404).end();
      return;
    }
    try {
      const content = fs.readFileSync(target);
      const extension = path.extname(target);
      const contentType = extension === ".html" ? "text/html; charset=utf-8"
        : extension === ".js" ? "text/javascript; charset=utf-8"
          : extension === ".css" ? "text/css; charset=utf-8"
            : "application/octet-stream";
      response.writeHead(200, { "Content-Type": contentType });
      response.end(content);
    } catch (_error) {
      response.writeHead(404).end();
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({ server, base: `http://127.0.0.1:${address.port}`, requests });
    });
  });
}

function lineReader(stream) {
  let buffer = "";
  const lines = [];
  const waiters = [];
  stream.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    for (;;) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) break;
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      const waiter = waiters.shift();
      if (waiter) waiter(line);
      else lines.push(line);
    }
  });
  return () => lines.length
    ? Promise.resolve(lines.shift())
    : new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Timed out waiting for test fixture")), 30000);
      waiters.push((line) => { clearTimeout(timer); resolve(line); });
    });
}

async function startProductionFixture() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), "tavern-history-"));
  const python = process.env.PYTHON_PATH || path.join(root, "venv", "bin", "python");
  const fixturePath = path.join(__dirname, "web_gui_history_fixture.py");
  const env = {
    ...process.env,
    PYTHONPATH: [root, path.join(root, "tests"), process.env.PYTHONPATH || ""]
      .filter(Boolean).join(path.delimiter),
  };
  const child = spawn(python, [fixturePath, dataRoot], {
    cwd: root,
    env,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const readLine = lineReader(child.stdout);
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
  const ready = await readLine();
  if (!ready.startsWith("READY http://")) {
    child.kill("SIGTERM");
    throw new Error(`Unexpected production fixture output: ${ready}\n${stderr}`);
  }
  return {
    child,
    dataRoot,
    base: ready.slice("READY ".length),
    stderr: () => stderr,
    readLine,
    async restartManagers() {
      child.stdin.write("RESTART\n");
      const line = await readLine();
      assert.equal(line, "RESTARTED", `fixture restart failed: ${line}\n${stderr}`);
    },
    async stop() {
      if (child.exitCode !== null) return;
      child.stdin.write("STOP\n");
      await Promise.race([
        new Promise((resolve) => child.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 10000)),
      ]);
      if (child.exitCode === null) child.kill("SIGKILL");
      fs.rmSync(dataRoot, { recursive: true, force: true });
    },
  };
}

async function readJson(response) {
  const body = await response.json();
  return { status: response.status(), body };
}

async function postJson(request, base, route, payload) {
  return readJson(await request.post(`${base}${route}`, {
    data: payload,
    headers: { Origin: base },
    timeout: 45000,
  }));
}

async function verifyProductionAccountFlow(browser, pageErrors) {
  const fixture = await startProductionFixture();
  const screenshotsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "tavern-history-ui-"));
  const alice = await browser.newContext({ acceptDownloads: true });
  const bob = await browser.newContext();
  const anonymous = await browser.newContext();
  try {
    const noAuth = [
      await anonymous.request.get(`${fixture.base}/api/matches`),
      await anonymous.request.get(`${fixture.base}/api/matches/detail?game_id=${ids.normal}`),
      await anonymous.request.get(`${fixture.base}/api/matches/download?game_id=${ids.normal}`),
      await anonymous.request.post(`${fixture.base}/api/matches/resume`, {
        data: { game_id: ids.normal, revision: 1 }, headers: { Origin: fixture.base },
      }),
      await anonymous.request.post(`${fixture.base}/api/matches/abandon`, {
        data: { game_id: ids.normal, revision: 1 }, headers: { Origin: fixture.base },
      }),
    ];
    assert.deepEqual(noAuth.map((response) => response.status()), [401, 401, 401, 401, 401],
      "every history API route must require an authenticated account");

    const registerAlice = await postJson(alice.request, fixture.base, "/api/account/register", {
      username: "History Alice", password: "local-password-123",
    });
    const registerBob = await postJson(bob.request, fixture.base, "/api/account/register", {
      username: "History Bob", password: "local-password-123",
    });
    assert.equal(registerAlice.status, 200, JSON.stringify(registerAlice.body));
    assert.equal(registerBob.status, 200, JSON.stringify(registerBob.body));
    const aliceId = registerAlice.body.account.id;

    const start = await postJson(alice.request, fixture.base, "/api/start", {
      nickname: "History Alice", locale: "enUS",
    });
    assert.equal(start.status, 200, JSON.stringify(start.body));
    assert.equal(start.body.mode, "match");
    const sessionIdBeforeRestart = start.body.session_id;
    let state = start.body;
    const mulligan = state.legal_actions.find((action) => action.type === "MULLIGAN");
    assert(mulligan, "the started match should expose a legal mulligan action");
    const moved = await postJson(alice.request, fixture.base, "/api/action", {
      session_id: state.session_id,
      revision: state.revision,
      action: mulligan,
    });
    assert.equal(moved.status, 200, JSON.stringify(moved.body));

    const aliceList = await readJson(await alice.request.get(
      `${fixture.base}/api/matches?offset=0&limit=20`,
    ));
    assert.equal(aliceList.status, 200, JSON.stringify(aliceList.body));
    assert.equal(aliceList.body.total, 1);
    const match = aliceList.body.matches[0];
    assert.equal(match.status, "in_progress");
    assert.equal(match.resumable, true);
    assert.equal(match.downloadable, false);
    const gameId = match.game_id;

    const detail = await readJson(await alice.request.get(
      `${fixture.base}/api/matches/detail?game_id=${encodeURIComponent(gameId)}`,
    ));
    assert.equal(detail.status, 200, JSON.stringify(detail.body));
    assert(detail.body.events.some((event) => event.type === "MULLIGAN"),
      "the accepted human decision should be durably visible as a public event");
    assert(!Object.hasOwn(detail.body, "log") && !Object.hasOwn(detail.body, "agent_state"),
      "history detail must not return the private replay envelope");
    assert(!JSON.stringify(detail.body).includes("resolved_deck_card_ids"));
    const publicOpponent = detail.body.snapshot?.observation?.opponent;
    assert(publicOpponent && !Object.hasOwn(publicOpponent, "hand")
      && !Object.hasOwn(publicOpponent, "deck") && !Object.hasOwn(publicOpponent, "secrets"),
    "history snapshot must not contain private opponent zones");

    const archiveDirectory = path.join(fixture.dataRoot, "users", aliceId, "matches");
    const archivePath = path.join(archiveDirectory,
      fs.readdirSync(archiveDirectory).find((name) => name.endsWith(".json")));
    const privateEnvelope = JSON.parse(fs.readFileSync(archivePath, "utf8"));
    const hiddenOpponentHand = privateEnvelope.log.checkpoint.state.players[1].hand;
    const hiddenCardIds = [...new Set(hiddenOpponentHand.map((card) => card.card_id).filter(Boolean))];
    assert(hiddenCardIds.length > 0, "the persisted opponent checkpoint should contain hidden cards");
    const observableCardIds = new Set((publicOpponent.field || []).map((card) => card.card_id));
    const privateCardIds = hiddenCardIds.filter((cardId) => !observableCardIds.has(cardId));
    assert(privateCardIds.length > 0, "fixture should have at least one still-hidden opponent card");
    const publicJson = JSON.stringify(detail.body);
    assert(privateCardIds.every((cardId) => !publicJson.includes(cardId)),
      "history API leaked an opponent card that is still in a hidden zone");

    const bobList = await readJson(await bob.request.get(`${fixture.base}/api/matches`));
    assert.equal(bobList.status, 200);
    assert.equal(bobList.body.total, 0, "another account must not list this match");
    const bobDetail = await bob.request.get(
      `${fixture.base}/api/matches/detail?game_id=${encodeURIComponent(gameId)}`,
    );
    assert.equal(bobDetail.status(), 404, "another account must not read match details");
    const bobDownload = await bob.request.get(
      `${fixture.base}/api/matches/download?game_id=${encodeURIComponent(gameId)}`,
    );
    assert.equal(bobDownload.status(), 404, "another account must not download a match");
    const bobResume = await postJson(bob.request, fixture.base, "/api/matches/resume", {
      game_id: gameId, revision: match.revision,
    });
    const bobAbandon = await postJson(bob.request, fixture.base, "/api/matches/abandon", {
      game_id: gameId, revision: match.revision,
    });
    assert.equal(bobResume.status, 404);
    assert.equal(bobAbandon.status, 404);

    const inProgressDownload = await alice.request.get(
      `${fixture.base}/api/matches/download?game_id=${encodeURIComponent(gameId)}`,
    );
    assert.equal(inProgressDownload.status(), 409, "unfinished logs must not download");

    await fixture.restartManagers();
    const page = await alice.newPage();
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${fixture.base}/history`, { waitUntil: "networkidle" });
    const card = page.locator(`[data-testid="history-match-card"][data-game-id="${gameId}"]`);
    await card.waitFor({ state: "visible" });
    await page.locator("#history-locale-zhCN").click();
    await card.locator(".history-view-button").click();
    await page.locator("#history-event-list .history-event").first().waitFor({ state: "visible" });
    assert((await page.locator("#history-detail").innerText()).includes("完成换牌"));
    const desktopScreenshot = path.join(screenshotsRoot, "history-1440-zh.png");
    const mobileScreenshot = path.join(screenshotsRoot, "history-390-zh.png");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: desktopScreenshot, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: mobileScreenshot, fullPage: true });

    const continueButton = card.locator(".history-continue-button");
    await continueButton.click();
    await page.waitForURL(`${fixture.base}/`, { timeout: 15000 });
    await page.waitForFunction(async () => {
      const response = await fetch("/api/state");
      const state = await response.json();
      return state.mode === "match" && state.session_id !== "";
    });
    const restoredState = await readJson(await alice.request.get(`${fixture.base}/api/state`));
    assert.equal(restoredState.status, 200, JSON.stringify(restoredState.body));
    assert.notEqual(restoredState.body.session_id, sessionIdBeforeRestart,
      "restart resume should create a new live session identity");
    assert(restoredState.body.revision >= moved.body.revision,
      "resume should retain the archived accepted-action prefix");

    await page.goto(`${fixture.base}/history`, { waitUntil: "networkidle" });
    const resumedCard = page.locator(`[data-testid="history-match-card"][data-game-id="${gameId}"]`);
    await resumedCard.waitFor({ state: "visible" });
    await resumedCard.locator(".history-abandon-button").click();
    await page.locator("#history-confirm").waitFor({ state: "visible" });
    await page.locator("#history-confirm-submit").click();
    await page.locator(`[data-testid="history-match-card"][data-game-id="${gameId}"] .history-match-status`)
      .filter({ hasText: "已放弃" }).waitFor({ state: "visible" });
    await page.locator("#history-status")
      .filter({ hasText: "对局已标记为放弃" }).waitFor({ state: "visible" });

    const downloadPromise = page.waitForEvent("download");
    await page.locator(`[data-game-id="${gameId}"] [data-testid="history-download"]`).click();
    const download = await downloadPromise;
    const rawPath = await download.path();
    const exported = JSON.parse(fs.readFileSync(rawPath, "utf8"));
    assert.equal(exported.game_id, gameId);
    assert.equal(exported.status, "abandoned",
      "download should reflect abandonment even though the raw in-progress log was retained");
    assert(exported.finished_at, "abandoned export should include the durable abandonment time");
    assert(exported.actions.some((entry) => entry.action.type === "MULLIGAN"));
    assert.deepEqual(pageErrors, [], `browser errors: ${pageErrors.join("; ")}`);

    return {
      accountOwnership: "passed",
      publicHistoryPrivacy: "passed",
      restartResume: "passed",
      abandonedDownload: "passed",
      gameId,
      archiveRevision: match.revision,
      resumedRevision: restoredState.body.revision,
      exportedStatus: exported.status,
      screenshots: [desktopScreenshot, mobileScreenshot],
    };
  } finally {
    await anonymous.close();
    await bob.close();
    await alice.close();
    await fixture.stop();
  }
}

async function main() {
  const fixture = await startFixture();
  const browser = await chromium.launch({
    executablePath: chrome,
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({ acceptDownloads: true });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(`${fixture.base}/history`, { waitUntil: "networkidle" });
    await page.locator(`[data-testid="history-match-card"][data-game-id="${ids.normal}"]`).waitFor({ state: "visible" });

    const sizes = [
      { width: 320, locale: "zhCN" },
      { width: 390, locale: "enUS" },
      { width: 900, locale: "zhCN" },
      { width: 1440, locale: "enUS" },
    ];
    for (const size of sizes) {
      await page.setViewportSize({ width: size.width, height: 1000 });
      await page.locator(`#history-locale-${size.locale}`).click();
      await page.waitForFunction((locale) => document.documentElement.lang === (locale === "enUS" ? "en" : "zh-CN"), size.locale);
      const dimensions = await page.evaluate(() => ({
        width: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        card: (() => {
          const element = document.querySelector("[data-game-id]");
          const rect = element.getBoundingClientRect();
          return { left: rect.left, right: rect.right };
        })(),
      }));
      assert.equal(dimensions.width, size.width);
      assert(dimensions.documentWidth <= size.width + 1,
        `${size.width}px ${size.locale} layout overflows to ${dimensions.documentWidth}px`);
      assert(dimensions.card.left >= 0 && dimensions.card.right <= size.width + 1,
        `${size.width}px match card escapes viewport: ${JSON.stringify(dimensions.card)}`);
    }

    await page.locator(`#history-locale-zhCN`).click();
    await page.locator(`[data-game-id="${ids.normal}"] .history-view-button`).click();
    await page.locator("#history-event-list .history-event").first().waitFor({ state: "visible" });
    const detailText = await page.locator("#history-detail").innerText();
    assert(detailText.includes("完成换牌"), "public event should be localized and rendered");
    assert(!detailText.includes("PRIVATE_OPPONENT_CARD"), "history must not render a hidden opponent card");

    await page.locator(`#history-locale-enUS`).click();
    await page.locator(`[data-game-id="${ids.broken}"] .history-continue-button`).click();
    await page.locator("#history-error").waitFor({ state: "visible" });
    assert((await page.locator("#history-error").innerText()).includes("archive signature mismatch"));
    assert((await page.locator("#history-error").innerText()).includes("Unable to continue this match"));

    await page.locator("#history-error").evaluate((node) => { node.hidden = true; });
    const arena = page.locator(`[data-game-id="${ids.arena}"]`);
    await arena.locator(".history-abandon-button").click();
    await page.locator("#history-confirm").waitFor({ state: "visible" });
    assert((await page.locator("#history-confirm-description").innerText()).includes("Arena will also count one loss"));
    await page.locator("#history-confirm-submit").click();
    const abandonedStatus = page.locator(`[data-testid="history-match-card"][data-game-id="${ids.arena}"] .history-match-status`);
    await abandonedStatus.filter({ hasText: "Abandoned" }).waitFor({ state: "visible" });
    await page.locator("#history-status").filter({ hasText: "marked abandoned" }).waitFor({ state: "visible" });

    const downloadPromise = page.waitForEvent("download");
    await page.locator(`[data-game-id="${ids.complete}"] [data-testid="history-download"]`).click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), new RegExp(ids.complete));

    await page.locator("#history-error").evaluate((node) => { node.hidden = true; });
    await page.locator(`[data-game-id="${ids.normal}"] .history-continue-button`).click();
    await page.waitForURL(`${fixture.base}/`, { timeout: 10000 });
    await page.locator("#fixture-resumed").waitFor({ state: "visible" });

    const resumeCalls = fixture.requests.filter((entry) => entry.pathname === "/api/matches/resume");
    const abandonCalls = fixture.requests.filter((entry) => entry.pathname === "/api/matches/abandon");
    const detailCalls = fixture.requests.filter((entry) => entry.pathname === "/api/matches/detail");
    const downloadCalls = fixture.requests.filter((entry) => entry.pathname === "/api/matches/download");
    assert.equal(resumeCalls.length, 2, "the UI should submit both resume attempts");
    assert.equal(abandonCalls.length, 1);
    assert.equal(detailCalls.length, 1);
    assert.equal(downloadCalls.length, 1);
    assert.deepEqual(pageErrors, [], `browser errors: ${pageErrors.join("; ")}`);

    const production = await verifyProductionAccountFlow(browser, pageErrors);

    console.log(JSON.stringify({
      result: "passed",
      viewports: sizes.map(({ width, locale }) => `${width}px/${locale}`),
      resumeAttempts: resumeCalls.length,
      abandonedArena: ids.arena,
      downloaded: download.suggestedFilename(),
      browserErrors: pageErrors,
      production,
    }));
  } finally {
    await browser.close();
    await new Promise((resolve) => fixture.server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
