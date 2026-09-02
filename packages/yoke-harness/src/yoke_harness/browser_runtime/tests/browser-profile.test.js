'use strict';

/**
 * Tests for the persistent browser profile.
 *
 * Run: node tests/browser-profile.test.js
 *
 * A daemon launched with --profile-dir opens Chromium's persistent context on
 * that directory, so a cookie one page sets is still there for the next
 * context the daemon hands out. A daemon launched without one keeps the
 * throwaway behavior. Both cases launch real Chromium — no Playwright mocking.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { createBrowserManager } = require('../src/browser-manager');
const { spawn } = require('child_process');

let testCount = 0;
let passCount = 0;
let failCount = 0;

function assert(condition, message) {
  testCount++;
  if (condition) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message}`);
  }
}

function makeProfileDir(label) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `yoke-browser-profile-${label}-`));
}

async function testPersistentContextKeepsCookies() {
  console.log('\n## Test: a profile directory keeps a cookie across launches');
  const profileDir = makeProfileDir('persist');

  const first = createBrowserManager({ profileDir });
  await first.launch();
  try {
    const page = await first.getPage('about:blank');
    await page.context().addCookies([{
      name: 'yoke_profile_probe',
      value: 'signed-in',
      url: 'https://profile.test',
      // A session cookie is dropped when the browser closes; only a cookie
      // with an expiry proves the profile itself carried it across launches.
      expires: Math.floor(Date.now() / 1000) + 3600,
    }]);
    assert(first.isConnected(), 'Persistent manager reports a connected context');
    assert(first.getBrowser() === null, 'Persistent launch exposes no Browser handle');
  } finally {
    await first.closeBrowser();
  }

  const second = createBrowserManager({ profileDir });
  await second.launch();
  try {
    const page = await second.getPage('about:blank');
    const cookies = await page.context().cookies('https://profile.test');
    assert(
      cookies.some((cookie) => cookie.name === 'yoke_profile_probe'),
      'Cookie set in the first launch is present in the second',
    );
  } finally {
    await second.closeBrowser();
  }
}

async function testNoProfileStillGetsCleanContext() {
  console.log('\n## Test: no profile directory still yields a working clean context');
  const manager = createBrowserManager({});
  await manager.launch();
  try {
    assert(manager.isConnected(), 'Throwaway manager reports a connected browser');
    const page = await manager.getPage('about:blank');
    const cookies = await page.context().cookies('https://profile.test');
    assert(cookies.length === 0, 'Clean context starts with an empty cookie jar');
  } finally {
    await manager.closeBrowser();
  }
}

function startDaemon(port, stateFile, extraArgs) {
  const daemonPath = path.join(__dirname, '..', 'src', 'daemon.js');
  const proc = spawn(
    process.execPath,
    [daemonPath, '--port', String(port), '--state-file', stateFile, ...extraArgs],
    { stdio: ['pipe', 'pipe', 'pipe'] },
  );
  let stderr = '';
  proc.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      try { proc.kill('SIGTERM'); } catch (_) {}
      clearInterval(poll);
      reject(new Error(`Daemon did not start within 15s. stderr: ${stderr}`));
    }, 15000);
    const poll = setInterval(() => {
      if (!fs.existsSync(stateFile)) return;
      try {
        const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
        clearInterval(poll);
        clearTimeout(timeout);
        resolve({ proc, state });
      } catch (_) {
        // mid-write
      }
    }, 200);
  });
}

function stopDaemon(proc) {
  return new Promise((resolve) => {
    proc.on('exit', resolve);
    proc.kill('SIGTERM');
    setTimeout(() => {
      try { proc.kill('SIGKILL'); } catch (_) {}
      resolve(-1);
    }, 5000);
  });
}

async function testDaemonRecordsProfileDir() {
  console.log('\n## Test: the daemon records the profile it launched on');
  const profileDir = makeProfileDir('state');
  const stateFile = path.join(os.tmpdir(), `daemon-profile-state-${process.pid}.json`);
  try { fs.unlinkSync(stateFile); } catch (_) {}
  const { proc, state } = await startDaemon(19420, stateFile, ['--profile-dir', profileDir]);
  try {
    assert(
      state.profileDir === profileDir,
      'State file names the profile directory the daemon opened',
    );
  } finally {
    await stopDaemon(proc);
  }
}

async function run() {
  console.log('# Browser Persistent Profile Tests\n');

  const tests = [
    testPersistentContextKeepsCookies,
    testNoProfileStillGetsCleanContext,
    testDaemonRecordsProfileDir,
  ];

  for (const test of tests) {
    try {
      await test();
    } catch (err) {
      testCount++;
      failCount++;
      console.log(`  FAIL: ${test.name} threw: ${err.message}`);
    }
  }

  console.log(`\n---\nResults: ${passCount}/${testCount} passed, ${failCount} failed`);
  process.exit(failCount > 0 ? 1 : 0);
}

run();
