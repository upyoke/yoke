'use strict';

// Run: node --test tests/open.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { EventEmitter } = require('events');
const { launchArgs, openIdentityWindow } = require('../src/open');

function fakeChild() {
  const child = new EventEmitter();
  child.pid = 4242;
  child.unref = () => { child.unrefed = true; };
  return child;
}

function profile() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-open-'));
}

test('the window uses the sign-in window flags plus a loopback DevTools port', () => {
  const args = launchArgs({ profileDir: '/p', url: 'https://example.com/a' });
  assert.ok(args.includes('--user-data-dir=/p'));
  assert.ok(args.includes('--password-store=basic'));
  assert.ok(args.includes('--use-mock-keychain'));
  assert.ok(args.includes('--remote-debugging-port=0'));
  assert.ok(!args.some((arg) => arg.startsWith('--headless')));
  assert.ok(!args.includes('--enable-automation'));
  assert.strictEqual(args[args.length - 1], 'https://example.com/a');
});

test('a new window reports the DevTools port Chromium recorded', async () => {
  const dir = profile();
  const child = fakeChild();
  let spawned;
  const opened = openIdentityWindow({ profileDir: dir, url: 'https://x.test/' }, {
    executablePath: () => '/chromium',
    spawnProcess: (binary, args, options) => {
      spawned = { binary, args, options };
      setTimeout(() => fs.writeFileSync(path.join(dir, 'DevToolsActivePort'), '43210\n/devtools/browser/x\n'), 5);
      return child;
    },
    pollMs: 5,
  });
  const result = await opened;
  assert.deepStrictEqual(result, { opened: 'new_window', devtools_port: 43210, pid: 4242 });
  assert.strictEqual(spawned.binary, '/chromium');
  assert.strictEqual(spawned.options.detached, true);
  assert.ok(child.unrefed);
});

test('a running browser that took the URL is reported, not refused', async () => {
  const dir = profile();
  fs.writeFileSync(path.join(dir, 'DevToolsActivePort'), '5555\n/devtools/browser/y\n');
  const child = fakeChild();
  const opened = openIdentityWindow({ profileDir: dir, url: 'https://x.test/' }, {
    executablePath: () => '/chromium',
    spawnProcess: () => { setTimeout(() => child.emit('exit', 0, null), 5); return child; },
    pollMs: 1000,
  });
  // The stale-looking file predates the spawn, so only the exit answers.
  assert.deepStrictEqual(await opened, { opened: 'running_browser', devtools_port: 5555 });
});

test('a failed launch and a silent one both refuse by name', async () => {
  const failing = fakeChild();
  await assert.rejects(openIdentityWindow({ profileDir: profile(), url: 'u' }, {
    executablePath: () => '/chromium',
    spawnProcess: () => { setTimeout(() => failing.emit('exit', 21, null), 5); return failing; },
  }), /browser_open_failed: Chromium exited with status 21/);
  let clock = 0;
  await assert.rejects(openIdentityWindow({ profileDir: profile(), url: 'u' }, {
    executablePath: () => '/chromium',
    spawnProcess: () => fakeChild(),
    pollMs: 1,
    readyMs: 50,
    now: () => (clock += 100),
  }), /browser_open_not_ready/);
});
