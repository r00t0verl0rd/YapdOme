// Requires Playwright + Chromium and a running local server.
// Run: node tests/test_dashboard_layout.js [http://127.0.0.1:8765]
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    for (const width of [1920, 1440, 1280, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(process.argv[2] || 'http://127.0.0.1:8765');
      await page.waitForFunction(() => document.querySelectorAll('.wave-lane i').length === 81);
      for (const pixelEnabled of [true, false]) {
        await page.locator('#pixelPuppetEnabled').setChecked(pixelEnabled);
        const layout = await page.evaluate(() => {
          const rect = selector => document.querySelector(selector).getBoundingClientRect();
          const scene = rect('.live-visual');
          const stream = rect('.stream');
          const table = rect('.dialogue-table');
          const portrait = rect('.hud-portrait');
          const wave = rect('.wave-lane');
          return {
            overflow: document.documentElement.scrollWidth - innerWidth,
            widthDifference: Math.abs(scene.width - stream.width),
            leftDifference: Math.abs(scene.left - stream.left),
            gap: stream.top - scene.bottom,
            tableFits: table.top < portrait.bottom && table.top > portrait.top + portrait.height / 2 && table.bottom <= wave.top + 1 && table.left >= scene.left && table.right <= scene.right,
            waves: [...document.querySelectorAll('.wave-lane')].map(wave => {
              const bounds = wave.getBoundingClientRect();
              const tile = wave.closest('.live-tile').getBoundingClientRect();
              const portrait = wave.previousElementSibling.getBoundingClientRect();
              return bounds.height >= 32 && bounds.top >= portrait.bottom && bounds.bottom <= tile.bottom;
            }),
          };
        });
        assert.ok(layout.overflow <= 1, `${width}: horizontal overflow`);
        assert.ok(layout.widthDifference <= 1 && layout.leftDifference <= 1, `${width}: panels misaligned`);
        assert.ok(layout.gap >= 0 && layout.gap <= 12, `${width}: gap between scene and stream`);
        assert.ok(layout.tableFits, `${width}: tabletop must cover lower torsos without covering waveforms`);
        assert.equal(layout.waves.length, 3);
        assert.ok(layout.waves.every(Boolean), `${width}: clipped waveform`);
      }
      await page.locator('#pixelPuppetEnabled').setChecked(true);
      assert.equal(await page.locator('.live-tile .pixel-controls').count(), 0);
      assert.equal(await page.locator('#cards .pixel-controls').count(), 3);
      await page.locator('#cards .pixel-mood').first().selectOption('joy');
      await page.evaluate(() => forceRenderCards());
      assert.equal(await page.locator('#cards .pixel-mood').first().inputValue(), 'joy');
      assert.equal(await page.locator('#cards .pixel-controls').count(), 3);
      await page.locator('#cards .pixel-mood').first().selectOption('auto');
      await page.locator('#voiceStudioButton').click();
      await page.waitForFunction(() => document.querySelector('#voiceSettings').open);
      assert.ok(await page.locator('#ttsBackend').isVisible(), 'Voice settings must remain accessible');
      console.log(`Dashboard ${width}px: OK (pixel/SVG, waveforms, alignment, voice studio)`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
