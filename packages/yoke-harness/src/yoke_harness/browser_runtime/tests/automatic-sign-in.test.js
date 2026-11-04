'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { signInSite } = require('../src/automatic-sign-in');

test('runtime never exposes a credential-bearing Playwright error', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-secret-test-'));
  const secret = 'planted-secret-never-in-evidence';
  const file = path.join(directory, 'secret');
  fs.writeFileSync(file, secret);
  const closed = [];
  const page = {
    setDefaultTimeout() {}, async goto() {}, url: () => 'https://shop.example/login',
    locator: () => ({ fill: async value => { throw Error(`fill(${value})`); } }),
    close: async () => closed.push(true),
  };
  try {
    const result = await signInSite({ newPage: async () => page }, {
      site: 'shop', origin: 'https://shop.example',
      sign_in: { url: 'https://shop.example/login', steps: [{ fill: '#pw', secret: 'password' }] },
    }, { password: file });
    assert.deepEqual(result, { site: 'shop', state: 'failed' });
    assert.ok(!JSON.stringify(result).includes(secret));
    assert.equal(closed.length, 1);
  } finally {
    fs.rmSync(directory, { recursive: true });
  }
});

test('a redirect cannot send a secret to another origin', async () => {
  let fills = 0;
  const page = {
    setDefaultTimeout() {}, async goto() {}, url: () => 'https://identity.example/login',
    locator: () => ({ fill: async () => { fills++; } }), async close() {},
  };
  const result = await signInSite({ newPage: async () => page }, {
    site: 'shop', origin: 'https://shop.example',
    sign_in: { url: 'https://shop.example/login', steps: [{ fill: 'input', secret: 'pw' }] },
  }, { pw: '/must-not-read' });
  assert.equal(result.state, 'failed');
  assert.equal(fills, 0);
});

function runScript(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(__dirname, '../src', script), ...args], {
      // A detached, headless child has no desktop or interactive stdin.
      detached: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, DISPLAY: '', WAYLAND_DISPLAY: '' },
    });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', reject);
    child.on('exit', code => resolve({ code, stdout, stderr, argv: child.spawnargs }));
  });
}

test('background Chromium signs in, reopens cookies, and sanitizes wrong-password evidence', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-sign-in-test-'));
  const secret = 'synthetic-test-account-password';
  const server = http.createServer((req, res) => {
    if (req.url === '/me') {
      res.writeHead((req.headers.cookie || '').includes('session=ok') ? 204 : 401);
      res.end();
    } else if (req.url === '/login' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        const accepted = new URLSearchParams(body).get('password') === secret;
        res.writeHead(303, {
          ...(accepted ? { 'Set-Cookie': 'session=ok; Path=/; Max-Age=3600' } : {}),
          Location: accepted ? '/home' : '/login?error=wrong',
        });
        res.end();
      });
    } else {
      res.setHeader('Content-Type', 'text/html');
      res.end('<form method="POST" action="/login"><input id="password" name="password" type="password"><button>Sign in</button></form>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const profile = path.join(directory, 'profile');
  const file = path.join(directory, 'password');
  const manifest = path.join(directory, 'manifest.json');
  const probe = { site: 'shop', url: `${origin}/me`, signed_in_status: 204 };
  fs.writeFileSync(file, secret, { mode: 0o600 });
  fs.writeFileSync(manifest, JSON.stringify({ sites: [{
    site: 'shop', origin, probe,
    sign_in: { url: `${origin}/login`, steps: [
      { fill: '#password', secret: 'password' }, { click: 'button' },
    ] }, secret_files: { password: file },
  }] }));
  try {
    const signed = await runScript('authorize-automatic.js', [profile, manifest]);
    assert.equal(signed.code, 0);
    assert.deepEqual(JSON.parse(signed.stdout).sites, [{ site: 'shop', state: 'signed_in' }]);
    assert.ok(!JSON.stringify(signed).includes(secret));
    const verified = await runScript('verify-sign-in.js', [
      '--profile-dir', profile, '--checks', JSON.stringify([probe]),
    ]);
    assert.equal(JSON.parse(verified.stdout).sites[0].state, 'signed_in');
    fs.writeFileSync(file, 'wrong-synthetic-password');
    const wrong = await runScript('authorize-automatic.js', [path.join(directory, 'wrong'), manifest]);
    assert.equal(wrong.code, 0);
    assert.deepEqual(JSON.parse(wrong.stdout).sites, [{ site: 'shop', state: 'expired' }]);
    assert.ok(!JSON.stringify(wrong).includes('wrong-synthetic-password'));
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true });
  }
});
