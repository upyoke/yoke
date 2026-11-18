'use strict';

/**
 * A browser left holding the profile is quit before the sign-in window opens.
 *
 * Chromium's SingletonLock (`<profile>/SingletonLock` -> `<host>-<pid>`)
 * makes a second launch forward its URLs to the holder as extra tabs and exit
 * 0, which read as the operator closing the window. These tests stand a live
 * dummy process in for that holder: it runs with the profile's
 * --user-data-dir, like a real Chromium, and the lock names it.
 */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { after, test } = require('node:test');
const { openSignInWindow } = require('../src/authorize');

// Every test is bounded, and every dummy dies with the suite, so code that
// never quits the holder fails instead of hanging.
const LIMIT = { timeout: 15000 };
const holders = new Set();
const profiles = new Set();
after(() => {
  for (const holder of holders) holder.kill('SIGKILL');
  for (const dir of profiles) fs.rmSync(dir, { recursive: true, force: true });
});

function tempProfile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-authorize-lock-'));
  profiles.add(dir);
  return dir;
}

/** A live process on `profileDir`; resolves once it is ready for signals. */
function startHolder(profileDir, { ignoreTerm }) {
  // The dummy also exits on its own, so nothing outlives an aborted run.
  const live = "console.log('ready'); setTimeout(() => process.exit(0), 30000);";
  const script = ignoreTerm ? `process.on('SIGTERM', () => {}); ${live}` : live;
  const holder = spawn(process.execPath, ['-e', script, '--', `--user-data-dir=${profileDir}`], {
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  holders.add(holder);
  holder.exitSignal = new Promise((resolve) => holder.on('exit', (code, signal) => resolve(signal)));
  fs.symlinkSync(`${os.hostname()}-${holder.pid}`, path.join(profileDir, 'SingletonLock'));
  return new Promise((resolve) => holder.stdout.once('data', () => resolve(holder)));
}

function fakeChild() {
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  child.pid = 4242;
  child.signals = [];
  child.kill = (signal) => {
    child.signals.push(signal);
    setImmediate(() => child.emit('exit', null, signal));
    return true;
  };
  return child;
}

test('a live profile holder is quit before the window spawns', LIMIT, async () => {
  const profileDir = tempProfile();
  const holder = await startHolder(profileDir, { ignoreTerm: false });
  let holderAtSpawn = 'not spawned';
  const child = fakeChild();
  const pending = openSignInWindow({ profileDir, urls: ['https://app.upyoke.com'] }, {
    spawnProcess: () => {
      holderAtSpawn = holder.exitCode !== null || holder.signalCode !== null ? 'exited' : 'alive';
      setImmediate(() => child.emit('exit', 0));
      return child;
    },
    executablePath: () => '/cache/chromium',
    platform: 'darwin', shutdownMs: 5000,
  });
  await pending;
  assert.equal(await holder.exitSignal, 'SIGTERM', 'the holder receives SIGTERM');
  assert.equal(holderAtSpawn, 'exited', 'the window spawns only after the holder exits');
});

test('a holder that ignores SIGTERM refuses with no spawn', LIMIT, async () => {
  const profileDir = tempProfile();
  const holder = await startHolder(profileDir, { ignoreTerm: true });
  let spawned = 0;
  try {
    await assert.rejects(openSignInWindow({ profileDir }, {
      spawnProcess: () => { spawned++; return fakeChild(); },
      executablePath: () => '/cache/chromium',
      platform: 'darwin', shutdownMs: 300,
    }), new RegExp(
      `^Error: authorization_profile_in_use: PID ${holder.pid} still holds ${profileDir}; quit it, then rerun$`,
    ));
    assert.equal(spawned, 0, 'no browser is spawned');
  } finally {
    holder.kill('SIGKILL');
  }
});

test('stop() signals the profile lock owner as well as the spawned PID', LIMIT, async () => {
  const profileDir = tempProfile();
  let holder;
  let ready = false;
  const child = fakeChild();
  child.kill = (signal) => { child.signals.push(signal); return true; }; // the launcher lingers
  const pending = openSignInWindow({ profileDir }, {
    spawnProcess: () => {
      // The launcher's child is the real browser, and it takes the lock.
      startHolder(profileDir, { ignoreTerm: false }).then((started) => {
        holder = started;
        ready = true;
        holder.on('exit', () => child.emit('exit', 0));
      });
      return child;
    },
    executablePath: () => '/cache/chromium',
    platform: 'linux', pollMs: 5, limitMs: 10000, shutdownMs: 5000,
    windowCount: async () => (ready ? 0 : 1),
  });
  await pending;
  assert.deepEqual(child.signals, ['SIGTERM'], 'the spawned PID receives SIGTERM');
  assert.equal(await holder.exitSignal, 'SIGTERM', 'the lock owner receives SIGTERM');
});
