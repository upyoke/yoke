'use strict';

/**
 * Per-site signed-in checks for one browser identity.
 *
 * Run: node tests/verify-sign-in.test.js
 */

const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { chromium } = require('playwright');
const { checkSites, checkLiveSites } = require('../src/verify-sign-in');

let testCount = 0;
let passCount = 0;
let failCount = 0;

function assertEqual(actual, expected, message) {
  testCount++;
  if (actual === expected) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
  }
}

// A site whose session cookie decides what /me and /dashboard answer.
function startSite() {
  const server = http.createServer((request, response) => {
    const signedIn = /session=ok/.test(request.headers.cookie || '');
    if (['/me', '/live-me'].includes(request.url)) {
      response.writeHead(signedIn ? 200 : 302, signedIn
        ? (request.url === '/live-me' ? { 'Set-Cookie': 'session=changed; Path=/' } : {})
        : { Location: '/login' });
      response.end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/html' });
    if (request.url === '/approval') return response.end('<h1>Approve</h1>');
    response.end(signedIn
      ? '<main><div id="account">Buyer</div></main>'
      : '<main><form><input type="password"><button>Sign in</button></form></main>');
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function readEndpoint(profile) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const marker = await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')
      .catch((error) => {
        if (error.code !== 'ENOENT') throw error;
        return '';
      });
    const [port, target] = marker.trim().split(/\r?\n/);
    if (target) return `ws://127.0.0.1:${port}${target}`;
    await delay(100);
  }
  throw new Error('Chromium did not publish its DevTools endpoint.');
}

async function checkOpenBrowser(origin, checks) {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'yoke-verify-'));
  const child = spawn(chromium.executablePath(), [
    `--user-data-dir=${profile}`, '--remote-debugging-port=0',
    '--headless=new', '--no-sandbox', '--no-first-run', `${origin}/approval`,
  ], { stdio: 'ignore' });
  const exited = once(child, 'exit');
  let fixture;
  try {
    const endpoint = await Promise.race([
      readEndpoint(profile),
      exited.then(([code]) => { throw new Error(`Chromium exited early: ${code}`); }),
    ]);
    fixture = await chromium.connectOverCDP(endpoint, { noDefaults: true });
    const context = fixture.contexts()[0];
    const approval = context.pages()[0];
    await approval.waitForURL(`${origin}/approval`);
    const other = await context.newPage();
    await other.goto(`${origin}/other`);
    await approval.bringToFront();

    let sites = await checkLiveSites(endpoint, checks);
    assertEqual(sites.map((s) => s.state).join(','), 'expired,expired',
      'open signed-out profile reports both probes as expired');
    await context.addCookies([{ name: 'session', value: 'ok', url: origin }]);
    sites = await checkLiveSites(endpoint, checks);
    assertEqual(sites.map((s) => s.state).join(','), 'signed_in,signed_in',
      'open profile passes both probes with its live session');
    assertEqual((await context.cookies(origin))[0].value, 'ok',
      'status probe response cannot change the live session cookie');
    assertEqual(context.pages().map((page) => page.url()).sort().join(','),
      [`${origin}/approval`, `${origin}/other`].join(','),
      'verification detaches and preserves existing tabs without leaving probe tabs');
    assertEqual(await approval.locator('h1').textContent(), 'Approve',
      'the approval page is still usable after attachment');
  } finally {
    if (fixture) await fixture.close();
    if (child.exitCode === null && child.signalCode === null) child.kill();
    await exited;
    await fs.rm(profile, { recursive: true, force: true, maxRetries: 5 });
  }
}

async function run() {
  console.log('=== Per-site sign-in checks ===');
  const site = await startSite();
  const origin = `http://127.0.0.1:${site.address().port}`;
  const browser = await chromium.launch({ headless: true });
  try {
    const checks = [
      { site: 'api', url: `${origin}/me`, signed_in_status: 200 },
      { site: 'app', url: `${origin}/dashboard`, signed_in_selector: '#account' },
      { site: 'gone', url: 'http://127.0.0.1:9/me', signed_in_status: 200 },
    ];

    console.log('\n## Test: a signed-out profile is expired on every reachable site');
    const signedOut = await browser.newContext();
    let sites = await checkSites(signedOut, checks);
    assertEqual(sites[0].state, 'expired', 'status probe does not follow the sign-in redirect');
    assertEqual(sites[1].state, 'expired', 'selector probe sees the sign-in wall');
    assertEqual(sites[2].state, 'unreachable', 'a site with no answer is unreachable, not expired');
    await signedOut.close();

    console.log('\n## Test: a signed-in profile passes each site separately');
    const signedIn = await browser.newContext();
    await signedIn.addCookies([{ name: 'session', value: 'ok', url: origin }]);
    sites = await checkSites(signedIn, checks.slice(0, 2));
    assertEqual(sites.map((s) => `${s.site}:${s.state}`).join(','),
      'api:signed_in,app:signed_in', 'each declared site is reported by name');
    await signedIn.close();

    await checkOpenBrowser(origin, [
      { ...checks[0], url: `${origin}/live-me` },
      checks[1],
    ]);
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    await browser.close();
    site.close();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();
