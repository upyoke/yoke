'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const { launchOptions } = require('../src/browser-executable');
const { executeStep } = require('../src/step-runner');
const { executeSignIn } = require('../src/step-actions/sign-in');

function entry(origin, secretFile) {
  return {
    site: 'shop', identity: 'buyer', project: 'acme', origin,
    probe: { site: 'shop', url: `${origin}/me`, signed_in_status: 204 },
    sign_in: { url: `${origin}/login`, steps: [
      { fill: '#password', secret: 'password' }, { click: '#submit' },
    ] }, secret_files: { password: secretFile },
  };
}

test('sign_in refuses a site without an automatic declaration', async () => {
  const outcome = await executeStep({}, { action: 'sign_in', site: 'shop' }, {
    baseUrl: 'https://shop.example',
  });
  assert.equal(outcome.success, false);
  assert.match(outcome.error, /browser_sign_in_step_not_automatic/);
});

test('credential-bearing Playwright exceptions never reach a step result', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-step-secret-'));
  const secret = 'planted-secret-not-in-a-step';
  const file = path.join(directory, 'password');
  fs.writeFileSync(file, secret);
  const page = {
    context: () => ({}), setDefaultTimeout() {}, async goto() {},
    url: () => 'https://shop.example/login',
    locator: () => ({ fill: async value => { throw Error(`fill value: ${value}`); } }),
  };
  try {
    const result = await executeSignIn(page, { site: 'shop' }, {
      signIn: entry('https://shop.example', file),
    });
    assert.equal(result.success, false);
    assert.match(result.error, /browser_automatic_sign_in_failed/);
    assert.ok(!JSON.stringify(result).includes(secret));
  } finally {
    fs.rmSync(directory, { recursive: true });
  }
});

test('expired session signs in again, asserts the app, then signs out without credential evidence', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-step-sign-in-'));
  const secret = 'synthetic-password-not-in-evidence';
  const file = path.join(directory, 'password');
  fs.writeFileSync(file, secret, { mode: 0o600 });
  const server = http.createServer((req, res) => {
    const signed = (req.headers.cookie || '').includes('session=ok');
    if (req.url === '/me') {
      res.writeHead(signed ? 204 : 401); res.end();
    } else if (req.url === '/logout') {
      res.writeHead(303, { 'Set-Cookie': 'session=; Path=/; Max-Age=0', Location: '/login' });
      res.end();
    } else if (req.url === '/login' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        const accepted = new URLSearchParams(body).get('password') === secret;
        res.writeHead(303, {
          ...(accepted ? { 'Set-Cookie': 'session=ok; Path=/' } : {}),
          Location: accepted ? '/home' : '/login',
        });
        res.end();
      });
    } else {
      res.setHeader('Content-Type', 'text/html');
      res.end(signed
        ? '<h1 id="account">Signed in</h1><a id="logout" href="/logout">Sign out</a>'
        : '<form method="POST" action="/login"><input id="password" type="password" name="password"><button id="submit">Sign in</button></form>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ ...launchOptions(), headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    const options = { baseUrl: origin, signIn: entry(origin, file) };
    const results = [];
    const steps = [
      { action: 'sign_in', site: 'shop' },
      { action: 'assert', target: '#account', check: 'visible' },
      { action: 'click', target: '#logout' },
      { action: 'assert', target: '#password', check: 'visible' },
      { action: 'sign_in', site: 'shop' },
      { action: 'assert', target: '#account', check: 'visible' },
      { action: 'click', target: '#logout' },
    ];
    for (const step of steps) {
      const result = await executeStep(page, step, options);
      results.push(result);
      assert.equal(result.success, true, JSON.stringify(result));
    }
    assert.deepEqual(results[0], {
      site: 'shop', identity: 'buyer', state: 'signed_in', success: true,
    });
    // Fail after filling too: neither probe details nor Playwright logs enter evidence.
    fs.writeFileSync(file, 'wrong-planted-password');
    results.push(await executeStep(page, { action: 'sign_in', site: 'shop' }, options));
    assert.match(results.at(-1).error, /browser_automatic_sign_in_failed/);
    fs.unlinkSync(file);
    results.push(await executeStep(page, { action: 'sign_in', site: 'shop' }, options));
    assert.match(results.at(-1).error, /browser_sign_in_secret_missing/);
    const evidence = path.join(directory, 'evidence.json');
    fs.writeFileSync(evidence, JSON.stringify({ step_results: results }));
    for (const credential of [secret, 'wrong-planted-password']) {
      assert.ok(!JSON.stringify(results).includes(credential));
      assert.ok(!fs.readFileSync(evidence, 'utf8').includes(credential));
    }
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true });
  }
});
