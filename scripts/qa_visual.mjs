// Multi-device visual + console QA for the CIA SPA.
//
// Drives the running app (hermetic backend serving the built SPA) with Playwright across every
// route, three viewports (desktop / tablet / mobile) and both themes, capturing a screenshot for
// each and a per-route sweep of console errors + failed network requests. Exits non-zero if any
// console error or failed request is seen — the regression gate the user asked for ("deep QA",
// "browser testing on different devices").
//
// Usage: APP=http://localhost:8092 node scripts/qa_visual.mjs
//   (chromium resolved from PLAYWRIGHT_BROWSERS_PATH or the bundled install)
import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// Playwright is installed globally in this sandbox (NODE_PATH); ESM bare-import can't see it, so
// resolve via require against the global modules dir.
const require = createRequire(import.meta.url);
const globalModules = process.env.NODE_PATH || '/opt/node22/lib/node_modules';
const { chromium } = require(`${globalModules}/playwright`);

const APP = process.env.APP || 'http://localhost:8092';
const OUT = '.qa/app';
mkdirSync(OUT, { recursive: true });

// Every built route (matches the router LIVE map + access routes).
const ROUTES = [
  'mission-control', 'explorer', 'value-chain', 'platforms', 'use-cases', 'knowledge-graph',
  'sow', 'stories', 'trace', 'news', 'trends', 'suggestions', 'benchmarks', 'digest',
  'lifecycle', 'vendors', 'clients', 'versions', 'diff', 'change-flags', 'gates', 'qa',
  'reasoning', 'chat', 'what-if', 'schema-mapping', 'settings', 'onboarding',
];
const VIEWPORTS = [
  { tag: 'desktop', width: 1440, height: 900 },
  { tag: 'tablet', width: 768, height: 1024 },
  { tag: 'mobile', width: 390, height: 844 },
];
const THEMES = ['light', 'dark'];

const report = { routes: {}, errors: [] };

async function settle(page) {
  await page.waitForTimeout(550);
  await page.evaluate(() => document.fonts?.ready).catch(() => {});
}

(async () => {
  const browser = await chromium.launch();
  for (const theme of THEMES) {
    for (const vp of VIEWPORTS) {
      // On tablet/mobile, only sweep the responsive-critical routes in dark to keep the matrix
      // sane; desktop gets the full route set in both themes.
      const routes =
        vp.tag === 'desktop'
          ? ROUTES
          : theme === 'light'
            ? ROUTES
            : ['mission-control', 'explorer', 'news', 'value-chain'];

      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
      const page = await ctx.newPage();
      page.on('console', (m) => {
        if (m.type() === 'error') {
          const text = m.text();
          // Firebase analytics + favicon noise is irrelevant in hermetic dev.
          if (/favicon|analytics|measurement/i.test(text)) return;
          report.errors.push({ where: page.url(), text });
        }
      });
      page.on('requestfailed', (r) => {
        report.errors.push({ where: page.url(), text: 'REQ FAIL ' + r.url() + ' ' + (r.failure()?.errorText ?? '') });
      });
      page.on('response', (r) => {
        if (r.status() >= 500) report.errors.push({ where: r.url(), text: 'HTTP ' + r.status() });
      });

      // Boot the SPA once, then drive routes by hash change (no reload) so the Zustand store —
      // which owns the theme — survives across routes. For the dark pass, toggle the theme via the
      // header button exactly as a user would (the store hydrates theme from server prefs, so
      // seeding localStorage alone would be overridden on mount).
      await page.goto(`${APP}/#/mission-control`, { waitUntil: 'domcontentloaded' });
      await settle(page);
      // Set the theme deterministically: the store hydrates theme from server prefs (which persist
      // across runs), so click the header toggle until the live data-theme matches the target.
      const themeNow = () =>
        page.evaluate(() => document.documentElement.getAttribute('data-theme'));
      for (let i = 0; i < 3 && (await themeNow()) !== theme; i++) {
        await page.click('[title="Toggle theme"]');
        await page.waitForTimeout(350);
      }
      if ((await themeNow()) !== theme) report.errors.push({ where: `${vp.tag}/${theme}`, text: 'theme set failed' });

      for (const r of routes) {
        const key = `${r}.${vp.tag}.${theme}`;
        try {
          await page.evaluate((route) => {
            window.location.hash = '#/' + route;
          }, r);
          await settle(page);
          await page.screenshot({ path: `${OUT}/${key}.png`, fullPage: false });
          report.routes[key] = 'ok';
        } catch (e) {
          report.routes[key] = 'ERR ' + String(e).slice(0, 100);
          report.errors.push({ where: key, text: String(e).slice(0, 160) });
        }
      }

      if (vp.tag === 'mobile' && theme === 'light') {
        await page.goto(`${APP}/#/mission-control`, { waitUntil: 'domcontentloaded' });
        await settle(page);
        await page.click('.hamburger').catch(() => {});
        await page.waitForTimeout(400);
        await page.screenshot({ path: `${OUT}/_navdrawer.mobile.light.png` });
      }
      await ctx.close();
    }
  }
  await browser.close();

  writeFileSync('.qa/console_report.json', JSON.stringify(report, null, 2));
  const nRoutes = Object.keys(report.routes).length;
  const nErr = report.errors.length;
  console.log(`captured ${nRoutes} route×viewport×theme shots → ${OUT}`);
  console.log(`console/network errors: ${nErr}`);
  for (const e of report.errors.slice(0, 25)) console.log('  ✗', e.where, '—', e.text);
  process.exit(nErr ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
