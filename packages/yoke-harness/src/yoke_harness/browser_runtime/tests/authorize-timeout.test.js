'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');
const { openSignInWindow } = require('../src/authorize');

for (const platform of ['darwin', 'linux', 'win32']) {
  for (const exitsOnTerm of [true, false]) {
    test(`${platform}: expired sign-in closes Chromium (graceful=${exitsOnTerm})`, async () => {
      const child = new EventEmitter();
      child.pid = 4242;
      const signals = [];
      child.kill = (signal) => {
        signals.push(signal);
        if ((exitsOnTerm && signal === 'SIGTERM') || signal === 'SIGKILL') {
          child.emit('exit', null, signal);
        }
        return true;
      };
      await assert.rejects(openSignInWindow({ profileDir: '/profiles/example' }, {
        spawnProcess: () => child,
        executablePath: () => '/cache/chromium',
        platform, windowCount: async () => 1,
        pollMs: 1, limitMs: 5, shutdownMs: 5,
      }), /authorization exceeded.*Reopen.*without --reset/);
      assert.deepEqual(signals, exitsOnTerm ? ['SIGTERM'] : ['SIGTERM', 'SIGKILL']);
    });
  }
}
