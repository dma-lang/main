// Live-auth TRANSITION QA — the flows route-by-route rendering sweeps (qa_visual) cannot reach.
//
// The three sign-in bugs all hid in the live Google flow, which automation can't click for real.
// This harness closes that blind spot: it stubs ONLY the two things that are Google's (the GSI
// script and /api/config, forced to live mode) and drives the REAL SPA against the REAL hermetic
// backend through every transition a user makes:
//   1. login → mission-control (Google's callback → token → /api/me → gate flip → redirect)
//   2. the popup race: a token-less /api/me 401 resolving AFTER sign-in must NOT bounce the
//      user back to the login page (this exact race shipped as "signed in but not redirected")
//   3. every sidebar item navigates (real clicks, distinct routes, shell intact)
//   4. deep-link reload (#/subcap/…) restores the session from the stored token
//   5. sign-out clears the token + cache and lands back on the login page
//
// Usage: APP=http://localhost:8092 node scripts/qa_transitions.mjs
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const globalModules = process.env.NODE_PATH || '/opt/node22/lib/node_modules';
const { chromium } = require(`${globalModules}/playwright`);

const APP = process.env.APP || 'http://localhost:8092';

const b64url = (s) => Buffer.from(s).toString('base64url');
// A JWT-shaped credential: the frontend only parses `exp` (the backend runs AUTH_MODE=dev here —
// live verification is covered by the backend test suite; this harness tests the TRANSITIONS).
const FAKE_JWT = [
  b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' })),
  b64url(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, email: 'qa@zennify.com' })),
  b64url('sig'),
].join('.');

// The GSI stub mirrors the real contract: initialize() captures the callback; renderButton()
// draws a clickable button; a click blurs+refocuses the window (exactly like the real popup)
// and then delivers the credential — so the focus-refetch race fires just as it does in prod.
const GSI_STUB = `
window.google = { accounts: { id: {
  initialize: (o) => { window.__gsiCb = o.callback; },
  renderButton: (parent) => {
    const b = document.createElement('button');
    b.setAttribute('data-test', 'gsi-stub');
    b.textContent = 'Continue with Google';
    b.onclick = () => {
      window.dispatchEvent(new Event('blur'));
      setTimeout(() => {
        window.dispatchEvent(new Event('focus'));
        window.__gsiCb({ credential: ${JSON.stringify(FAKE_JWT)} });
      }, 30);
    };
    parent.replaceChildren(b);
  },
  disableAutoSelect: () => {},
}}};`;

// STALE-BUILD TRIPWIRE (same as qa_visual): transitions against an old bundle prove nothing.
{
  const { readFileSync } = await import('node:fs');
  const wanted = readFileSync(new URL('../frontend/dist/index.html', import.meta.url), 'utf8')
    .match(/index-[\w-]+\.js/)?.[0];
  const served = (await (await fetch(APP + '/')).text()).match(/index-[\w-]+\.js/)?.[0];
  if (!wanted || served !== wanted) {
    console.error(
      `STALE BUILD: server serves ${served ?? 'nothing'} but frontend/dist has ${wanted}.\n` +
        'Restart the server with STATIC_DIR=<repo>/frontend/dist (see scripts/dev_up.sh).',
    );
    process.exit(2);
  }
  console.log(`build check: serving ${served} (matches frontend/dist)`);
}

const failures = [];
const consoleErrors = [];
let passed = 0;
function check(name, ok, detail = '') {
  if (ok) {
    passed += 1;
    console.log(`PASS  ${name}`);
  } else {
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`);
    console.log(`FAIL  ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

page.on('console', (m) => {
  // The deliberate token-less 401s below surface as resource-load console errors — expected.
  if (m.type() === 'error' && !/401|Failed to load resource/.test(m.text())) {
    consoleErrors.push(m.text());
  }
});
page.on('pageerror', (e) => consoleErrors.push(String(e)));

// Force live mode (the backend itself runs dev) and serve the GSI stub in place of Google.
await page.route('**/api/config', (route) =>
  route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      auth_mode: 'live',
      auth_email_domain: 'zennify.com',
      google_client_id: 'qa-stub-client-id.apps.googleusercontent.com',
    }),
  }),
);
await page.route('https://accounts.google.com/gsi/client*', (route) =>
  route.fulfill({ contentType: 'application/javascript', body: GSI_STUB }),
);
// Reproduce the production race shape: a token-less /api/me is SLOW and then 401s (it must never
// unseat a sign-in that completes while it is in flight); token-carrying requests pass through.
await page.route('**/api/me', async (route) => {
  const authed = !!route.request().headers()['authorization'];
  if (route.request().method() === 'GET' && !authed) {
    await sleep(800);
    return route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 401, message: 'auth required' } }),
    });
  }
  return route.fallback();
});

// ---- 1. The login page renders Google's button (config → live → GSI render path) ----
await page.goto(`${APP}/#/login`, { waitUntil: 'domcontentloaded' });
const stub = page.locator('[data-test="gsi-stub"]');
await stub.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => {});
check('login renders the Google button (live config + GSI host)', await stub.isVisible());

// ---- 2. Sign in → gate flips → mission control; the stale 401 must not bounce it ----
await stub.click();
// the app serialises filter state into the hash (#/mission-control?v=v7) — match the route part
const onMissionControl = async () =>
  (await page.evaluate(() => location.hash)).startsWith('#/mission-control') &&
  (await page.locator('nav.sidebar').isVisible());
let landed = false;
for (let t = 0; t < 15_000 && !landed; t += 250) {
  await sleep(250);
  landed = await onMissionControl();
}
check('sign-in lands on mission control (callback → /api/me → gate flip)', landed);
await sleep(2_000); // outlive the 800ms stale 401 + any refetch fallout
check(
  '…and STAYS there: the racing token-less 401 cannot bounce the session',
  await onMissionControl(),
);

// ---- 3. Every sidebar item navigates (real clicks, the shell never breaks) ----
const itemCount = await page.locator('nav.sidebar .navitem').count();
const seen = new Set();
for (let i = 0; i < itemCount; i += 1) {
  const item = page.locator('nav.sidebar .navitem').nth(i);
  const title = (await item.getAttribute('title')) ?? `item ${i}`;
  await item.click();
  await sleep(350);
  const hash = await page.evaluate(() => location.hash);
  const shellOk = await page.locator('nav.sidebar').isVisible();
  if (!hash || hash === '#/login' || !shellOk) {
    check(`sidebar → ${title}`, false, `hash=${hash} shell=${shellOk}`);
  } else {
    seen.add(hash);
  }
}
check(
  `sidebar walk: ${itemCount} items → ${seen.size} distinct routes, shell intact`,
  itemCount > 20 && seen.size === itemCount,
  `items=${itemCount} distinct=${seen.size}`,
);

// ---- 4. Deep-link reload restores the session from the stored token ----
await page.goto(`${APP}/#/subcap/P2C3.5.1`, { waitUntil: 'domcontentloaded' });
const deepOk = await page
  .getByText('P2C3.5.1', { exact: false })
  .first()
  .isVisible({ timeout: 15_000 })
  .catch(() => false);
check('deep-link reload (#/subcap/…) restores the session + focuses the subcap', deepOk);

// ---- 5. Sign out clears the session and lands on the login page ----
await page.evaluate(() => {
  location.hash = '#/settings';
});
const signOutBtn = page.getByRole('button', { name: /sign out/i });
await signOutBtn.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {});
check('settings exposes Sign out', await signOutBtn.isVisible());
await signOutBtn.click();
const backAtLogin = await page
  .locator('[data-test="gsi-stub"]')
  .isVisible({ timeout: 15_000 })
  .catch(() => false);
const tokenCleared = await page.evaluate(() => sessionStorage.getItem('cia_id_token') === null);
check('sign-out → login page, token cleared', backAtLogin && tokenCleared);

await browser.close();

if (consoleErrors.length) {
  console.log(`\nunexpected console errors (${consoleErrors.length}):`);
  for (const e of consoleErrors.slice(0, 10)) console.log('  ', e.slice(0, 200));
}
console.log(
  `\n${failures.length === 0 && consoleErrors.length === 0 ? 'ALL TRANSITIONS PASS' : 'TRANSITION FAILURES'} — ${passed} passed, ${failures.length} failed, ${consoleErrors.length} console errors`,
);
process.exit(failures.length === 0 && consoleErrors.length === 0 ? 0 : 1);
