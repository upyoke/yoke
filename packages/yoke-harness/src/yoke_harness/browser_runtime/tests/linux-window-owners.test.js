'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');

const { windowOwnerPids } = require('../src/linux-window-owners');
const { linuxWindowCount, openSignInWindow } = require('../src/authorize');

const PROFILE = '/home/op/.yoke/browser/profiles/acme';

function fakeProc(processes) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-proc-'));
  fs.mkdirSync(path.join(root, 'self'));
  for (const { pid, ppid, comm = 'chrome', argv } of processes) {
    const dir = path.join(root, String(pid));
    fs.mkdirSync(dir);
    fs.writeFileSync(path.join(dir, 'stat'), `${pid} (${comm}) S ${ppid} ${pid} ${pid} 0`);
    fs.writeFileSync(path.join(dir, 'cmdline'), `${argv.join('\0')}\0`);
  }
  return root;
}

// A launcher shim (PID 100) whose child (PID 101) is the browser that owns the
// window, plus that browser's renderer, an unrelated Chromium, and a second
// main process re-parented away from the launcher but still on this profile.
const LAUNCHER_TREE = [
  { pid: 100, ppid: 1, comm: 'chromium-browse', argv: ['/bin/sh', '/usr/bin/chromium-browser', `--user-data-dir=${PROFILE}`] },
  { pid: 101, ppid: 100, argv: ['/usr/lib/chromium/chrome', `--user-data-dir=${PROFILE}`] },
  { pid: 102, ppid: 101, argv: ['/usr/lib/chromium/chrome', '--type=renderer', `--user-data-dir=${PROFILE}`] },
  { pid: 200, ppid: 1, argv: ['/usr/lib/chromium/chrome', '--user-data-dir=/home/op/other'] },
  { pid: 300, ppid: 1, comm: 'chrome (x)', argv: [`/snap/chromium/chrome --user-data-dir=${PROFILE} --no-first-run`] },
];

test('owners are the spawned tree and this profile\'s main processes, not renderers or other profiles', () => {
  const procRoot = fakeProc(LAUNCHER_TREE);
  const owners = windowOwnerPids(100, PROFILE, { procRoot, uid: process.getuid() });
  assert.deepEqual(owners.sort((a, b) => a - b), [100, 101, 300]);
});

test('processes owned by another user never count', () => {
  const procRoot = fakeProc(LAUNCHER_TREE);
  assert.deepEqual(windowOwnerPids(100, PROFILE, { procRoot, uid: process.getuid() + 1 }), [100]);
});

test('a launcher PID whose child owns the window counts as opened', async () => {
  const procRoot = fakeProc(LAUNCHER_TREE);
  const count = await linuxWindowCount(100, PROFILE, {
    ownerPids: (pid, profileDir) => windowOwnerPids(pid, profileDir, { procRoot }),
    searchWindows: async (pid) => (pid === 101 ? ['77594625', '77594630'] : []),
  });
  assert.equal(count, 2);
});

test('the sign-in window stays open past the start limit when the launcher\'s child owns it', async () => {
  const { EventEmitter } = require('events');
  const child = new EventEmitter();
  child.pid = 100;
  const signals = [];
  child.kill = (signal) => { signals.push(signal); child.emit('exit', null, signal); return true; };
  const procRoot = fakeProc(LAUNCHER_TREE);
  let checks = 0;
  await openSignInWindow({ profileDir: PROFILE }, {
    spawnProcess: () => child,
    executablePath: () => '/usr/bin/chromium-browser',
    platform: 'linux', pollMs: 1, startMs: 5, limitMs: 5000,
    windowCount: (pid, profileDir) => linuxWindowCount(pid, profileDir, {
      ownerPids: (root, dir) => windowOwnerPids(root, dir, { procRoot }),
      // The window stays open well past startMs, then the operator closes it.
      searchWindows: async (pid) => (pid === 101 && checks++ < 40 ? ['77594625'] : []),
    }),
  });
  assert.ok(checks >= 40, 'the window was polled past the start limit');
  assert.deepEqual(signals, ['SIGTERM'], 'closing the window ends the launcher gracefully');
});
