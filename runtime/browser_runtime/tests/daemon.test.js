'use strict';

/**
 * Tests for browser daemon core — state file, auth, health, stop.
 *
 * Run: node tests/daemon.test.js
 *
 * Companion file ``daemon-lifecycle.test.js`` covers idle timeout,
 * stale-state cleanup, early-exit rejection, and response shape.
 *
 * These tests launch real daemon instances on ephemeral ports and verify
 * behavior via HTTP requests. No mocking of Playwright — tests exercise
 * the real stack.
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const os = require('os');
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

function assertIncludes(haystack, needle, message) {
  testCount++;
  if (haystack && haystack.includes(needle)) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message} (expected to include ${JSON.stringify(needle)})`);
  }
}

function httpRequest(options, postData) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ statusCode: res.statusCode, body: JSON.parse(data) });
        } catch (_) {
          resolve({ statusCode: res.statusCode, body: data });
        }
      });
    });
    req.on('error', reject);
    if (postData) req.write(postData);
    req.end();
  });
}

function startDaemon(port, extraArgs = []) {
  const stateFileIdx = extraArgs.indexOf('--state-file');
  const stateFile = stateFileIdx >= 0
    ? extraArgs[stateFileIdx + 1]
    : path.join(os.tmpdir(), `daemon-test-${port}-${process.pid}.json`);
  if (stateFileIdx < 0) {
    try { fs.unlinkSync(stateFile); } catch (_) {}
  }

  const daemonPath = path.join(__dirname, '..', 'src', 'daemon.js');
  const args = [daemonPath, '--port', String(port), '--state-file', stateFile, ...extraArgs.filter((_, i) => stateFileIdx < 0 || (i !== stateFileIdx && i !== stateFileIdx + 1))];
  const proc = spawn(process.execPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });

  let stderr = '';
  proc.stderr.on('data', (chunk) => { stderr += chunk.toString(); });

  const hasPreexistingStateFile = stateFileIdx >= 0 && fs.existsSync(stateFile);

  return new Promise((resolve, reject) => {
    let settled = false;
    let poll = null;

    function finishResolve(result) {
      if (settled) return;
      settled = true;
      if (poll) clearInterval(poll);
      clearTimeout(timeout);
      resolve(result);
    }

    function finishReject(error) {
      if (settled) return;
      settled = true;
      if (poll) clearInterval(poll);
      clearTimeout(timeout);
      reject(error);
    }

    const timeout = setTimeout(() => {
      try { proc.kill('SIGTERM'); } catch (_) {}
      finishReject(new Error(`Daemon did not start within 15s. stderr: ${stderr}`));
    }, 15000);

    poll = setInterval(() => {
      if (fs.existsSync(stateFile)) {
        try {
          const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
          if (hasPreexistingStateFile && state.pid !== proc.pid) {
            return;
          }
          finishResolve({ proc, stateFile, token: state.token, state });
        } catch (_) {
          // mid-write
        }
      }
    }, 200);

    proc.on('exit', (code, signal) => {
      if (settled) return;
      const exitReason = signal ? `signal ${signal}` : `code ${code}`;
      finishReject(new Error(`Daemon exited before startup completed (${exitReason}). stderr: ${stderr}`));
    });
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

let nextPort = 19220;
function getPort() {
  return nextPort++;
}

async function testStateFileShape() {
  console.log('\n## Test: State file has correct shape');
  const port = getPort();
  const { proc, state } = await startDaemon(port);

  try {
    assert(typeof state.pid === 'number', 'pid is a number');
    assert(typeof state.token === 'string' && state.token.length > 0, 'token is a non-empty string');
    assertIncludes(state.endpoint, `http://127.0.0.1:${port}`, 'endpoint contains host and port');
    assertEqual(state.browserType, 'chromium', 'browserType is chromium');
    assert(typeof state.startedAt === 'string', 'startedAt is a string');
    assertEqual(state.health, 'healthy', 'health is healthy');
    assertEqual(state.port, port, 'port matches');
  } finally {
    await stopDaemon(proc);
  }
}

async function testStateFilePermissions() {
  console.log('\n## Test: State file has 0600 permissions');
  const port = getPort();
  const { proc, stateFile } = await startDaemon(port);

  try {
    const stats = fs.statSync(stateFile);
    const mode = stats.mode & 0o777;
    assertEqual(mode, 0o600, `permissions are 0600 (got ${mode.toString(8)})`);
  } finally {
    await stopDaemon(proc);
  }
}

async function testBearerAuthRejects() {
  console.log('\n## Test: Bearer auth rejects unauthorized requests');
  const port = getPort();
  const { proc, token } = await startDaemon(port);

  try {
    const r1 = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    assertEqual(r1.statusCode, 401, 'No auth header returns 401');

    const r2 = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer wrong-token' },
    });
    assertEqual(r2.statusCode, 401, 'Wrong token returns 401');

    const r3 = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    });
    assertEqual(r3.statusCode, 200, 'Correct token returns 200');
  } finally {
    await stopDaemon(proc);
  }
}

async function testHealthEndpoint() {
  console.log('\n## Test: /api/health returns expected shape');
  const port = getPort();
  const { proc, token } = await startDaemon(port);

  try {
    const r = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    });
    assertEqual(r.statusCode, 200, 'health returns 200');
    assertEqual(r.body.success, true, 'success is true');
    assertEqual(r.body.data.health, 'healthy', 'health is healthy');
    assert(typeof r.body.data.uptime_ms === 'number', 'uptime_ms is a number');
    assertEqual(r.body.data.browser_connected, true, 'browser_connected is true');
  } finally {
    await stopDaemon(proc);
  }
}

async function testStopEndpoint() {
  console.log('\n## Test: /api/stop triggers clean shutdown');
  const port = getPort();
  const { proc, stateFile, token } = await startDaemon(port);

  await httpRequest({
    hostname: '127.0.0.1', port, path: '/api/stop', method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
  });

  await new Promise((resolve) => {
    const t = setTimeout(() => resolve(), 5000);
    proc.on('exit', () => { clearTimeout(t); resolve(); });
  });

  assert(!fs.existsSync(stateFile), 'State file removed after stop');
}

async function run() {
  console.log('# Browser Daemon Tests — Core\n');

  const tests = [
    testStateFileShape,
    testStateFilePermissions,
    testBearerAuthRejects,
    testHealthEndpoint,
    testStopEndpoint,
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
