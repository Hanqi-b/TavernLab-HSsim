"use strict";
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { initialState, startFixture } = require("./web_gui_arena_browser.cjs");

async function main() {
  const state = initialState();
  state.format_id = "custom_v1";
  state.formats = [
    { id: "custom_v1", label: "自选版", max_wins: 7, max_losses: 3 },
    { id: "wild_2016_09_02", label: "2016 历史版", max_wins: 12, max_losses: 3 },
  ];
  const fixture = await startFixture(state);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/opt/google/chrome/chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(fixture.base);
    const select = page.locator('[data-testid="arena-format"]');
    await select.waitFor();
    await page.locator('[data-testid="arena-nickname"]').fill("History tester");
    assert.equal(await page.locator('[data-testid="arena-start"]').isDisabled(), true);
    const large = page.locator('[data-action="toggle-pack"][data-pack-size="large"]');
    const small = page.locator('[data-action="toggle-pack"][data-pack-size="small"]');
    for (let i = 0; i < 4; i++) await large.nth(i).click();
    for (let i = 0; i < 2; i++) await small.nth(i).click();
    assert.equal(await page.locator('[data-testid="arena-start"]').isDisabled(), false);
    await select.selectOption("wild_2016_09_02");
    await page.locator('[data-testid="arena-historical-pool"]').waitFor();
    assert.equal(await page.locator('[data-action="toggle-pack"]').count(), 0);
    assert.equal(await page.locator('.arena-historical-set-list [data-set-id]').count(), 9);
    assert.match(await page.locator('[data-testid="arena-offer-policy-notice"]').textContent(), /近似/);
    assert.match(await page.locator('[data-testid="arena-combat-limitation"]').textContent(), /当前 Fireplace/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    // Switching back preserves the original custom controls and budget gating.
    await select.selectOption("custom_v1");
    assert.equal(await page.locator('[data-testid="arena-start"]').isDisabled(), false);
    assert.equal(Number(await page.locator(".arena-budget-ring strong").textContent()), 14);
    assert.equal(await page.locator('[data-testid="arena-classic-lock"]').count(), 1);
    await select.selectOption("wild_2016_09_02");
    await page.locator('[data-testid="arena-start"]').click();
    await page.locator('[data-testid="arena-hero-offer"]').waitFor();
    assert.equal(fixture.startRequest.format_id, "wild_2016_09_02");
    assert.deepEqual(fixture.startRequest.set_ids, []);
    assert.equal(await select.count(), 0, "format cannot change in an active run");
    await page.locator('[data-action="choose-hero"]').first().click();
    for (let count = 1; count <= 30; count++) {
      await page.locator('[data-testid="arena-card-offer"] [data-action="pick-card"]').first().click();
      await page.waitForFunction(expected => document.querySelectorAll('[data-testid="arena-deck"] .arena-deck-row').length === expected, count);
    }
    await page.locator('[data-testid="arena-battle"]').waitFor();
    assert.match(await page.locator('[data-testid="arena-record-target"]').textContent(), /12/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log("arena format browser acceptance passed");
  } finally {
    await page.close();
    await browser.close();
    fixture.server.close();
  }
}
main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
