#!/usr/bin/env node
/* Browser acceptance checks for battle control geometry and hit testing. */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const readline = require("node:readline");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const fixture = path.join(__dirname, "web_gui_controls_layout_fixture.py");
const python = process.env.FIREPLACE_GUI_PYTHON || path.join(root, "venv/bin/python");
const chrome = process.env.CHROME_PATH || "/opt/google/chrome/chrome";
const timeout = Number(process.env.FIREPLACE_GUI_TIMEOUT_MS || 30000);
const screenshotDir = process.env.FIREPLACE_GUI_SCREENSHOT_DIR || "";

function startFixture(locale) {
  const child = spawn(python, ["-u", fixture, "--port", "0", "--locale", locale], {
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
        // Engine diagnostics can precede the fixture readiness JSON.
      }
    });
    child.stderr.on("data", (chunk) => logs.push(String(chunk)));
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
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
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

function overlaps(left, right) {
  return left && right && left.x < right.x + right.width && left.x + left.width > right.x &&
    left.y < right.y + right.height && left.y + left.height > right.y;
}

function oldLayoutCss() {
  return `
    .extras-row { width: auto !important; max-width: 16% !important; }
    .opponent-panel .extras-row { left: 34% !important; }
    .self-panel .extras-row { left: 32.5% !important; }
    /* The pre-fix stack let the hand layer sit above the control lane when
       the self panel was not promoted for a hero interaction. */
    .self-panel.promote-interaction { z-index: 4 !important; }
    .power-row { bottom: 18% !important; left: 76% !important; width: 10.5% !important; }
    .power-copy { bottom: -30px !important; left: -65% !important; width: 230% !important; }
    @media (max-width: 700px) {
      .extras-row { max-width: 24% !important; }
      .opponent-panel .extras-row { left: 34% !important; }
      .self-panel .extras-row { left: 16% !important; }
      .power-row { bottom: 25% !important; left: 75% !important; width: 19% !important; }
    }
  `;
}

async function layoutState(page) {
  return page.evaluate(() => {
    const rect = (node) => {
      const value = node?.getBoundingClientRect();
      return value && value.width > 0 && value.height > 0
        ? { x: value.x, y: value.y, width: value.width, height: value.height }
        : null;
    };
    const power = document.querySelector(".power-card");
    const powerBox = rect(power);
    const powerCopy = rect(document.querySelector(".power-copy"));
    const heroBoxes = [
      rect(document.getElementById("self-hero-row")),
      rect(document.getElementById("opponent-hero-row")),
    ];
    const selfWeapon = document.querySelector('[data-testid="self-weapon"]');
    const opponentWeapon = document.querySelector('[data-testid="opponent-weapon"]');
    const selfResources = [...document.querySelectorAll("#self-panel .self-resources > *")].map(rect);
    const opponentResources = [...document.querySelectorAll("#opponent-panel .player-resources > *")].map(rect);
    const statusNodes = [...document.querySelectorAll("#self-hero-status > *, #opponent-hero-status > *")].map(rect);
    const endTurn = rect(document.getElementById("end-turn-button"));
    const hand = [...document.querySelectorAll(".hand-card")].map(rect);
    const board = [...document.querySelectorAll("#self-board .board-card")].map(rect);
    const opponentBoard = [...document.querySelectorAll("#opponent-board .board-card")].map(rect);
    const boardStats = [...document.querySelectorAll("#self-board .stat")].map(rect);
    const opponentBoardStats = [...document.querySelectorAll("#opponent-board .stat")].map(rect);
    const powerPoint = powerBox
      ? { x: powerBox.x + powerBox.width / 2, y: powerBox.y + powerBox.height / 2 }
      : null;
    const pointNode = powerPoint ? document.elementFromPoint(powerPoint.x, powerPoint.y) : null;
    const weaponStack = (selector) => {
      const name = document.querySelector(`${selector} .weapon-name`);
      const box = name?.getBoundingClientRect();
      return box ? document.elementsFromPoint(box.x + box.width / 2, box.y + box.height / 2)
        .slice(0, 8).map((node) => node.dataset?.testid || node.id || node.className || node.tagName) : [];
    };
    return {
      power: powerBox,
      powerCopy,
      selfWeapon: rect(selfWeapon),
      opponentWeapon: rect(opponentWeapon),
      selfResources,
      opponentResources,
      statusNodes,
      endTurn,
      heroes: heroBoxes,
      hand,
      board,
      opponentBoard,
      boardStats,
      opponentBoardStats,
      handCount: hand.length,
      boardCount: board.length,
      opponentBoardCount: opponentBoard.length,
      powerHit: Boolean(pointNode && pointNode.closest(".power-card")),
      powerStack: powerPoint
        ? document.elementsFromPoint(powerPoint.x, powerPoint.y).slice(0, 7).map((node) =>
          node.dataset?.testid || node.id || node.className || node.tagName)
        : [],
      weaponName: [...document.querySelectorAll('[data-testid="self-weapon"] .weapon-name, [data-testid="opponent-weapon"] .weapon-name')]
        .map((node) => ({ text: node.textContent, width: node.getBoundingClientRect().width,
          height: node.getBoundingClientRect().height, scrollHeight: node.scrollHeight,
          clientHeight: node.clientHeight, whiteSpace: getComputedStyle(node).whiteSpace,
          textOverflow: getComputedStyle(node).textOverflow })),
      weaponStats: [...document.querySelectorAll('[data-testid="self-weapon"] .weapon-stats, [data-testid="opponent-weapon"] .weapon-stats')]
        .map((node) => ({ text: node.textContent, children: node.children.length,
          width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height })),
      powerCopyPointerEvents: getComputedStyle(document.querySelector(".power-copy")).pointerEvents,
      selfWeaponStack: weaponStack('[data-testid="self-weapon"]'),
      opponentWeaponStack: weaponStack('[data-testid="opponent-weapon"]'),
    };
  });
}

function assertNewLayout(state, label) {
  assert(state.power, `hero power must be rendered at ${label}`);
  assert.equal(state.handCount, 10, `fixture must render ten hand cards at ${label}`);
  assert.equal(state.boardCount, 7, `fixture must render seven board minions at ${label}`);
  assert.equal(state.opponentBoardCount, 7, `fixture must render seven opponent board minions at ${label}`);
  assert(state.powerHit, `hero power circle must be topmost at ${label}: ${JSON.stringify(state.powerStack)}`);
  assert(state.heroes[0] && state.heroes[1], `both heroes must be rendered at ${label}`);
  assert(!overlaps(state.selfWeapon, state.heroes[0]),
    `own weapon must clear own hero at ${label}: ${JSON.stringify({ weapon: state.selfWeapon, hero: state.heroes[0] })}`);
  assert(!overlaps(state.opponentWeapon, state.heroes[1]),
    `opponent weapon must clear opponent hero at ${label}: ${JSON.stringify({ weapon: state.opponentWeapon, hero: state.heroes[1] })}`);
  for (const resource of state.selfResources) {
    assert(!overlaps(state.selfWeapon, resource),
      `own weapon must clear mana/deck controls at ${label}: ${JSON.stringify({ weapon: state.selfWeapon, resource })}`);
  }
  for (const resource of state.opponentResources) {
    assert(!overlaps(state.opponentWeapon, resource),
      `opponent weapon must clear mana/deck controls at ${label}: ${JSON.stringify({ weapon: state.opponentWeapon, resource })}`);
  }
  for (const control of [...state.statusNodes, state.endTurn].filter(Boolean)) {
    assert(!overlaps(state.selfWeapon, control) && !overlaps(state.opponentWeapon, control),
      `weapon chips must clear status/end-turn controls at ${label}: ${JSON.stringify({ own: state.selfWeapon, opponent: state.opponentWeapon, control })}`);
  }
  assert(String(state.selfWeaponStack[0]).includes("weapon-name") &&
    state.selfWeaponStack.some((value) => String(value).includes("self-weapon")),
    `own weapon name must remain hit-testable above resources at ${label}: ${JSON.stringify(state.selfWeaponStack)}`);
  assert(String(state.opponentWeaponStack[0]).includes("weapon-name") &&
    state.opponentWeaponStack.some((value) => String(value).includes("opponent-weapon")),
    `opponent weapon name must remain hit-testable above resources at ${label}: ${JSON.stringify(state.opponentWeaponStack)}`);
  const allBoardContent = [...state.board, ...state.opponentBoard, ...state.boardStats, ...state.opponentBoardStats];
  for (const weapon of [state.selfWeapon, state.opponentWeapon]) {
    assert(weapon, `both weapon chips must be rendered at ${label}`);
    for (const other of allBoardContent) {
      assert(!overlaps(weapon, other), `weapon must clear board/stat targets at ${label}: ${JSON.stringify({ weapon, other })}`);
    }
  }
  const forbidden = [...state.hand, ...allBoardContent];
  for (const box of [state.power, state.powerCopy]) {
    assert(box, `hero power copy/control must have a rendered box at ${label}`);
    for (const other of forbidden) {
      assert(!overlaps(box, other), `hero power must clear board/hand at ${label}: ${JSON.stringify({ box, other })}`);
    }
  }
  assert.equal(state.powerCopyPointerEvents, "none", `hero power copy must not intercept board clicks at ${label}`);
  for (const name of state.weaponName) {
    assert(name.width > 0 && name.height > 0, `weapon name must be visible at ${label}`);
    assert.equal(name.whiteSpace, "normal", `weapon name must wrap at ${label}`);
    assert.equal(name.textOverflow, "clip", `weapon name must not ellipsize at ${label}`);
    assert(name.scrollHeight <= name.clientHeight + 2,
      `weapon name must fit its wrapped box at ${label}: ${JSON.stringify(name)}`);
  }
  for (const stats of state.weaponStats) {
    assert(stats.children >= 3 && stats.width > 0 && stats.height > 0,
      `weapon stats must stay compact and visible at ${label}: ${JSON.stringify(stats)}`);
  }
}

async function assertHoveredHandClear(page, label) {
  for (let index = 0; index < 10; index += 1) {
    await page.locator('.hand-card[data-testid="hand-card"]').nth(index).hover({ force: true });
    await page.waitForTimeout(220);
    const state = await layoutState(page);
    assertNewLayout(state, `${label}-hover-${index + 1}`);
  }
  await page.mouse.move(1, 1);
}

async function runLocale(browser, locale) {
  const server = startFixture(locale);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const diagnostics = [];
  try {
    const fixtureInfo = await server.ready;
    await context.route("**/api/account/session", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, account: { id: "controls-layout", username: "Layout tester" }, legacy_available: false }),
    }));
    await context.route("**/assets/**", (route) => route.fulfill({ status: 404, body: "" }));
    await context.route("**/api/decks*", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ decks: [] }),
    }));
    const page = await context.newPage();
    page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error}`));
    page.on("console", (message) => {
      if (message.type() === "error" && !message.text().includes("404")) diagnostics.push(`console: ${message.text()}`);
    });
    await page.goto(fixtureInfo.url, { waitUntil: "domcontentloaded" });
    await page.getByTestId("action-submit").waitFor({ state: "visible", timeout });
    await page.getByTestId("action-submit").click();
    await page.getByTestId("self-weapon").waitFor({ state: "visible", timeout });
    await page.locator('#self-board .board-card').nth(6).waitFor({ state: "visible", timeout });
    await page.locator('.hand-card[data-testid="hand-card"]').nth(9).waitFor({ state: "visible", timeout });

    const ownName = await page.locator('[data-testid="self-weapon"] .weapon-name').textContent();
    const opponentName = await page.locator('[data-testid="opponent-weapon"] .weapon-name').textContent();
    assert.match(ownName || "", /测试超长武器名称/);
    assert.match(opponentName || "", /VeryLongEnglishWeaponName/);
    await page.getByTestId("self-weapon").click();
    await page.locator("#card-modal").waitFor({ state: "visible", timeout });
    await page.locator("#modal-close").click();

    // Establish the old collision in the same deterministic state before
    // removing the temporary style and checking the new geometry.
    const oldStyle = await page.addStyleTag({ content: oldLayoutCss() });
    await page.waitForTimeout(50);
    const oldState = await layoutState(page);
    assert.equal(oldState.selfWeapon !== null, true, `old own weapon must render at ${locale}`);
    assert.equal(oldState.opponentWeapon !== null, true, `old opponent weapon must render at ${locale}`);
    assert(overlaps(oldState.selfWeapon, oldState.heroes[0]),
      `old own weapon lane should overlap the hero at ${locale}`);
    assert(overlaps(oldState.opponentWeapon, oldState.heroes[1]),
      `old opponent weapon lane should overlap the hero at ${locale}`);
    const oldHandCollision = oldState.hand.find((card) => overlaps(oldState.power, card));
    assert(oldHandCollision, `old hero power lane should collide with the ten-card hand at ${locale}`);
    const oldPoint = {
      x: Math.max(oldState.power.x, oldHandCollision.x) + 2,
      y: Math.max(oldState.power.y, oldHandCollision.y) + 2,
    };
    const oldStack = await page.evaluate(({ x, y }) =>
      document.elementsFromPoint(x, y).slice(0, 8).map((node) => node.dataset?.testid || node.id || node.className || node.tagName), oldPoint);
    assert(String(oldStack[0]).includes("hand-card"),
      `old hand must win hit testing over the hero power in the collision: ${JSON.stringify(oldStack)}`);
    await oldStyle.evaluate((node) => node.remove());

    for (const width of [320, 390, 700, 900, 1440]) {
      await page.setViewportSize({ width, height: width <= 700 ? 844 : 900 });
      await page.evaluate(() => window.fireplaceWebGui.loadState(true));
      await page.waitForTimeout(100);
      assertNewLayout(await layoutState(page), `${locale}-${width}`);
      if (screenshotDir && locale === "zhCN" && (width === 390 || width === 1440)) {
        await page.screenshot({
          path: path.join(screenshotDir, `controls-layout-${width}.png`),
          fullPage: true,
        });
      }
      if (width >= 900) await assertHoveredHandClear(page, `${locale}-${width}`);
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => window.fireplaceWebGui.loadState(true));
    await page.waitForTimeout(100);
    const sourceId = await page.locator(".power-card.sourceable").getAttribute("data-entity-id");
    assert(sourceId, "hero power must remain a legal source with ten hand cards");
    const actionRequest = page.waitForRequest((request) =>
      request.url().endsWith("/api/action") && request.method() === "POST", { timeout });
    const actionResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/action") && response.request().method() === "POST", { timeout });
    await page.locator(".power-card.sourceable").click();
    await page.locator("#opponent-hero-row .targetable").click();
    // Target selection submits a unique targeted action immediately; waiting
    // for the confirmation button would race the in-flight request.
    const [request, response] = await Promise.all([actionRequest, actionResponse]);
    const requestBody = request.postDataJSON();
    assert.equal(requestBody.action.type, "USE_HERO_POWER", `power click must dispatch the legal action: ${JSON.stringify(requestBody)}`);
    assert.equal(String(requestBody.action.source_entity_id), String(sourceId));
    const responseBody = await response.json();
    const responseSnapshot = responseBody.snapshot || responseBody;
    assert.equal(responseSnapshot.observation?.self?.mana, 7,
      `hero power should spend two mana from the fixture's nine remaining mana: ${JSON.stringify(responseSnapshot.observation?.self)}`);
    assert.deepEqual(diagnostics, [], `browser diagnostics for ${locale}`);
    return { locale, result: "PASS" };
  } finally {
    await context.close();
    await stopFixture(server.child);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: chrome, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
  try {
    for (const locale of ["zhCN", "enUS"]) console.log(JSON.stringify(await runLocale(browser, locale)));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
