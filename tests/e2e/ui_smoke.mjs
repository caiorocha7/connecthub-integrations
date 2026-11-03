// Browser smoke test of the Angular UI against the running stack (requires seeded demo data).
// Usage: cd tests/e2e && npm install && CHROME_PATH=... node ui_smoke.mjs [output-dir]
// Logs in as the demo user, visits every screen, replays a failure, checks mobile layout and
// fails on console errors, page errors or API responses >= 400.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';

const BASE = process.env.CONNECTHUB_UI ?? 'http://localhost:4230';
const OUT = process.argv[2] ?? 'ui-smoke-output';
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH ?? '/usr/bin/google-chrome',
  headless: true,
  args: ['--no-sandbox'],
  defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 1 },
});
const page = await browser.newPage();
const problems = [];
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
page.on('console', (m) => {
  if (m.type() === 'error' && !m.text().includes('fonts.g')) problems.push(`console(${page.url()}): ${m.text()}`);
});
page.on('response', (r) => {
  if (r.url().includes('/api/') && r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`);
});

const shot = async (name) => {
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: `${OUT}/${name}.png` });
};

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
await shot('01-login');
await page.type('#email', 'demo@example.com');
await page.type('#password', 'Demo@12345');
await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle0' }), page.click('button[type=submit]')]);
if (!page.url().includes('/dashboard')) problems.push(`login did not reach dashboard: ${page.url()}`);
await page.waitForSelector('ch-kpi');
await shot('02-dashboard');

const pages = [
  ['03-endpoints', '/endpoints', 'table'],
  ['05-destinations', '/destinations', 'table'],
  ['06-transforms', '/transforms', '.rule'],
  ['08-events', '/events', 'table'],
  ['10-deliveries', '/deliveries', 'table'],
  ['12-failures', '/failures', '.tabs'],
  ['13-simulator', '/simulator', '.mode'],
  ['14-organization', '/organization', 'table'],
  ['15-settings', '/settings', 'form'],
];
for (const [name, path, sel] of pages) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle0' });
  try {
    await page.waitForSelector(sel, { timeout: 8000 });
  } catch {
    problems.push(`missing ${sel} on ${path}`);
  }
  await shot(name);
}

// Detail pages via clicks
await page.goto(`${BASE}/endpoints`, { waitUntil: 'networkidle0' });
await page.click('tbody tr.clickable');
await page.waitForSelector('.route-form, .copy-field');
await shot('04-endpoint-detail');

await page.goto(`${BASE}/transforms`, { waitUntil: 'networkidle0' });
await page.click('.rule h2 a');
await page.waitForSelector('.mapping');
await shot('07-transform-editor');

await page.goto(`${BASE}/events`, { waitUntil: 'networkidle0' });
await page.click('tbody tr.clickable');
await page.waitForSelector('ch-json');
await shot('09-event-detail');

await page.goto(`${BASE}/deliveries?status=SUCCEEDED`, { waitUntil: 'networkidle0' });
// pick a delivery that had retries if possible
const rows = await page.$$('tbody tr.clickable');
let picked = false;
for (const row of rows) {
  const txt = await row.evaluate((el) => el.textContent ?? '');
  if (/\b[2-4]\/4\b/.test(txt)) {
    await row.click();
    picked = true;
    break;
  }
}
if (!picked && rows[0]) await rows[0].click();
await page.waitForSelector('.timeline');
await shot('11-delivery-detail');

// Replay a failed delivery from the failures page
await page.goto(`${BASE}/failures`, { waitUntil: 'networkidle0' });
const replayBtn = await page.$('tbody .btn:not(.ghost)');
if (replayBtn) {
  await replayBtn.click();
  await new Promise((r) => setTimeout(r, 1500));
  const toast = await page.$eval('.toasts', (el) => el.textContent ?? '').catch(() => '');
  if (!toast.includes('reenfileirada')) problems.push(`replay toast missing: "${toast}"`);
}

// Mobile layout
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle0' });
await shot('16-mobile-dashboard');

// Logout
await page.setViewport({ width: 1440, height: 900 });
await page.click('button[aria-label="Sair"]');
await page.waitForSelector('#email', { timeout: 8000 }).catch(() => problems.push('logout did not return to login'));

await browser.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'UI smoke OK — no console/page errors');
if (problems.length) process.exit(1);
