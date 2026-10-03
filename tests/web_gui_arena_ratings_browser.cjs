"use strict";
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { initialState, startFixture } = require("./web_gui_arena_browser.cjs");

function draftState(locale, format, tie = false) {
  const state = initialState();
  Object.assign(state, {
    mode: "draft", run_id: "rating-fixture", revision: 2, locale,
    format_id: format, nickname: "Rating tester",
    hero: { id: "HERO_08", name: "Mage", class: "MAGE", card_set: "BASIC" },
    max_wins: format === "custom_v1" ? 7 : 12, max_losses: 3,
    rating_source: { name: "Lightforge", as_of: "2016-09-02", card_class: "MAGE" },
    card_offer: ["0", "130", tie ? "130*" : "60*"].map((raw, index) => ({
      id: `AT_00${index + 1}`, name: `Test card ${index + 1}`, text: "Test text",
      class: "NEUTRAL", card_set: "TGT", quality_status: "YELLOW",
      arena_rating: { raw, numeric: Number(raw.replace("*", "")),
        starred: raw.endsWith("*"), over_100: Number(raw.replace("*", "")) > 100,
        source: "Lightforge", as_of: "2016-09-02", card_class: "MAGE" },
    })),
  });
  return state;
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/opt/google/chrome/chrome", headless: true });
  try {
    for (const locale of ["zhCN", "enUS"]) {
      for (const width of [375, 1440]) {
        const state = draftState(locale, "wild_2016_09_02", width === 1440);
        const fixture = await startFixture(state);
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        await page.addInitScript(value => localStorage.setItem("fireplace.locale", value), locale);
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        try {
          await page.goto(fixture.base);
          await page.locator('[data-testid="arena-rating"]').first().waitFor();
          const badges = await page.locator(".arena-rating-badge").allTextContents();
          assert.deepEqual(badges, state.card_offer.map(c => `${locale === "zhCN" ? "评分" : "Rating"} ${c.arena_rating.raw}`));
          assert.equal(await page.locator(".arena-rating-highest").count(), width === 1440 ? 2 : 1);
          assert.equal(await page.locator('.arena-rating-highest').first().locator("..").getAttribute("data-rating-numeric"), "130");
          const source = await page.locator('[data-testid="arena-rating-source"]').textContent();
          assert.match(source, /Lightforge/);
          assert.match(source, /2016-09-02/);
          assert.match(source, /MAGE|Mage|法师/);
          assert.match(source, /\*/);
          assert.equal(await page.locator(".arena-quality-badge").count(), 3);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
          if (process.env.ARENA_RATING_SCREENSHOT_DIR) {
            const path = require("node:path");
            const fs = require("node:fs");
            fs.mkdirSync(process.env.ARENA_RATING_SCREENSHOT_DIR, { recursive: true });
            await page.screenshot({ path: path.join(process.env.ARENA_RATING_SCREENSHOT_DIR, `arena-ratings-${locale}-${width}.png`), fullPage: true });
          }
          const choice = page.locator('[data-action="pick-card"]').first();
          assert.match(await choice.getAttribute("aria-label"), /(?:评分|Rating) 0/);
          // The score is informational: even the zero-scored offer is selectable.
          if (width === 375) await page.locator('.arena-rating-badge').first().click();
          else { await choice.focus(); await page.keyboard.press("Enter"); }
          await page.waitForFunction(() => document.querySelectorAll('.arena-deck-row').length === 1);
          assert.equal(state.deck[0].id, "AT_001");
          assert.deepEqual(errors, []);
        } finally {
          await page.close();
          fixture.server.close();
        }
      }
    }
    // Even stale rating-shaped fields cannot enable the custom-mode UI.
    const fixture = await startFixture(draftState("zhCN", "custom_v1"));
    const page = await browser.newPage();
    try {
      await page.goto(fixture.base);
      await page.locator('[data-action="pick-card"]').first().waitFor();
      assert.equal(await page.locator('[data-testid="arena-rating"]').count(), 0);
      assert.equal(await page.locator('[data-testid="arena-rating-source"]').count(), 0);
    } finally { await page.close(); fixture.server.close(); }
    console.log("arena player rating browser acceptance passed (two locales, desktop/mobile, ties, custom isolation)");
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
