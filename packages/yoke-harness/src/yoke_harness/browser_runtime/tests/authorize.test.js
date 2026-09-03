'use strict';

/**
 * Tests for the operator sign-in window.
 *
 * Run: node tests/authorize.test.js
 *
 * The window must be a plain browser process, not a Playwright context.
 * Google's sign-in refuses an automation-controlled browser ("Couldn't sign
 * you in. This browser or app may not be secure"), so a profile opened
 * through launchPersistentContext cannot be signed into through Google at
 * all. These tests hold that shape: the daemon's own Chromium binary, the
 * profile directory, and no automation-shaped flags.
 *
 * They also hold the cookie-encryption switches. Chromium drops any stored
 * cookie it cannot decrypt when it loads a profile, and Playwright always
 * launches in a different key domain from a default browser launch, so a
 * window opened without those switches wrote a sign-in the daemon then threw
 * away -- silently, leaving a profile that looked authorized and rendered
 * signed out.
 */

const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');
const authorize = require('../src/authorize');

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

// Flags that would mark the window as automation-controlled, plus the
// headless shape a human cannot sign in through.
const AUTOMATION_FLAGS = [
  '--enable-automation',
  '--remote-debugging-port',
  '--remote-debugging-pipe',
  '--headless',
];

// Chromium takes its cookie-encryption key from the platform credential
// store; these two switches select the same key domain Playwright's own
// launch uses. Both sides must agree or the daemon cannot read the sign-in.
const COOKIE_ENCRYPTION_SWITCHES = ['--password-store=basic', '--use-mock-keychain'];

function fakeChild() {
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  return child;
}

async function testSpawnsTheDaemonsBinaryOnTheProfile() {
  console.log('\n## Test: the window is the daemon\'s own Chromium on the profile');
  const spawned = [];
  const child = fakeChild();
  const pending = authorize.openSignInWindow(
    { profileDir: '/profiles/acme', url: 'https://app.upyoke.com' },
    {
      spawnProcess: (binary, args, options) => {
        spawned.push({ binary, args, options });
        return child;
      },
      executablePath: () => '/cache/chromium/Google Chrome for Testing',
    },
  );
  child.emit('exit', 0);
  await pending;

  assert(spawned.length === 1, 'Exactly one browser process is spawned');
  assert(
    spawned[0].binary === '/cache/chromium/Google Chrome for Testing',
    'Spawns the resolved Chromium executable path',
  );
  assert(
    spawned[0].args.includes('--user-data-dir=/profiles/acme'),
    'Opens the project profile directory',
  );
  assert(
    spawned[0].args.includes('https://app.upyoke.com'),
    'Passes the starting URL as a plain argument',
  );
  assert(
    spawned[0].args.includes('--no-first-run')
      && spawned[0].args.includes('--no-default-browser-check'),
    'Skips the first-run and default-browser prompts',
  );
  const automation = spawned[0].args.filter(
    (arg) => AUTOMATION_FLAGS.some((flag) => arg.startsWith(flag)),
  );
  assert(
    automation.length === 0,
    `Carries no automation-shaped flags (saw: ${automation.join(', ') || 'none'})`,
  );
  const missing = COOKIE_ENCRYPTION_SWITCHES.filter(
    (flag) => !spawned[0].args.includes(flag),
  );
  assert(
    missing.length === 0,
    `Writes cookies in the daemon's key domain (missing: ${missing.join(', ') || 'none'})`,
  );
}

async function testMatchesPlaywrightsOwnCookieEncryptionSwitches() {
  console.log('\n## Test: the key domain is the one Playwright still launches with');
  const libDir = path.join(
    path.dirname(require.resolve('playwright-core/package.json')), 'lib',
  );
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.js')) files.push(full);
    }
  };
  walk(libDir);
  const sources = files.map((file) => fs.readFileSync(file, 'utf8'));
  for (const flag of COOKIE_ENCRYPTION_SWITCHES) {
    assert(
      sources.some((source) => source.includes(flag)),
      `Playwright still launches Chromium with ${flag}`,
    );
  }
}

async function testOmitsTheUrlWhenNoneIsGiven() {
  console.log('\n## Test: no starting URL leaves the browser on its own new tab');
  const spawned = [];
  const child = fakeChild();
  const pending = authorize.openSignInWindow(
    { profileDir: '/profiles/acme', url: '' },
    {
      spawnProcess: (binary, args) => {
        spawned.push(args);
        return child;
      },
      executablePath: () => '/cache/chromium/Google Chrome for Testing',
    },
  );
  child.emit('exit', 0);
  await pending;

  assert(
    spawned[0].every((arg) => arg.startsWith('--')),
    'Passes only flags when there is no starting URL',
  );
}

async function testReportsANonZeroBrowserExit() {
  console.log('\n## Test: a browser that fails to open is reported, not swallowed');
  const child = fakeChild();
  const pending = authorize.openSignInWindow(
    { profileDir: '/profiles/acme' },
    {
      spawnProcess: () => child,
      executablePath: () => '/cache/chromium/Google Chrome for Testing',
    },
  );
  child.stderr.emit('data', Buffer.from('profile is already in use\n'));
  child.emit('exit', 21);

  let message = '';
  try {
    await pending;
  } catch (err) {
    message = err.message;
  }
  assert(message.includes('status 21'), 'Names the browser exit status');
  assert(
    message.includes('profile is already in use'),
    'Carries the browser\'s own diagnostic',
  );
}

async function testNeverUsesAPlaywrightContext() {
  console.log('\n## Test: the sign-in window never opens a Playwright context');
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'authorize.js'), 'utf8',
  );
  const calls = source.split('\n').filter(
    (line) => line.includes('launchPersistentContext') && !line.trim().startsWith('*'),
  );
  assert(
    calls.length === 0,
    `No launchPersistentContext call (saw: ${calls.join(' | ') || 'none'})`,
  );
}

async function testResolvesTheSameBinaryTheDaemonDrives() {
  console.log('\n## Test: the binary is the one the daemon itself launches');
  const expected = require('playwright').chromium.executablePath();

  assert(
    authorize.resolveExecutablePath() === expected,
    'Resolves Playwright\'s Chromium, whose keychain entry encrypts the profile',
  );
}

async function run() {
  console.log('# Browser Authorize Tests\n');

  const tests = [
    testSpawnsTheDaemonsBinaryOnTheProfile,
    testMatchesPlaywrightsOwnCookieEncryptionSwitches,
    testOmitsTheUrlWhenNoneIsGiven,
    testReportsANonZeroBrowserExit,
    testNeverUsesAPlaywrightContext,
    testResolvesTheSameBinaryTheDaemonDrives,
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
