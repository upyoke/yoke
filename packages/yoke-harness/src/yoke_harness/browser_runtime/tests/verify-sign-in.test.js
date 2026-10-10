'use strict';

/**
 * Per-site signed-in checks for one browser identity.
 *
 * Run: node tests/verify-sign-in.test.js
 */

const http = require('http');
const { chromium } = require('playwright');
const { checkSites } = require('../src/verify-sign-in');

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
    if (request.url === '/me') {
      response.writeHead(signedIn ? 200 : 302, signedIn ? {} : { Location: '/login' });
      response.end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end(signedIn
      ? '<main><div id="account">Buyer</div></main>'
      : '<main><button>Sign in</button></main>');
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
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
