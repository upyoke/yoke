'use strict';

/**
 * Tests for browser daemon lifecycle — idle timeout, stale state,
 * early-exit rejection, and response shape.
 *
 * Run: node tests/daemon-lifecycle.test.js
 *
 * Companion file ``daemon.test.js`` covers the state-file shape,
 * permissions, bearer auth, health, and stop endpoints.
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

let nextPort = 19320;
function getPort() {
  return nextPort++;
}

async function testIdleTimeout() {
  console.log('\n## Test: Idle timeout triggers shutdown');
  const port = getPort();
  // Use a very short idle timeout (1 second)
  const { proc, stateFile } = await startDaemon(port, ['--idle-timeout', '1000']);

  // Wait for idle shutdown (up to 5 seconds)
  await new Promise((resolve) => {
    const t = setTimeout(() => resolve(), 5000);
    proc.on('exit', () => { clearTimeout(t); resolve(); });
  });

  assert(!fs.existsSync(stateFile), 'State file removed after idle timeout');
}

async function testStaleStateCleanup() {
  console.log('\n## Test: Stale state file is cleaned up on restart');
  const port = getPort();
  const stateFile = path.join(os.tmpdir(), `daemon-test-stale-${port}-${process.pid}.json`);

  // Write a stale state file with a dead PID
  const staleState = {
    pid: 999999999,
    token: 'stale-token',
    endpoint: `http://127.0.0.1:${port}`,
    browserType: 'chromium',
    startedAt: '2024-01-01T00:00:00Z',
    health: 'crashed',
    port,
  };
  fs.writeFileSync(stateFile, JSON.stringify(staleState), { mode: 0o600 });

  // Start daemon — should detect stale state and clean up
  const { proc, state } = await startDaemon(port, ['--state-file', stateFile]);

  try {
    assert(state.token !== 'stale-token', 'New token generated (not stale)');
    assertEqual(state.health, 'healthy', 'Health is healthy after restart');
    assert(state.pid === proc.pid, 'PID matches current process');
  } finally {
    await stopDaemon(proc);
    try { fs.unlinkSync(stateFile); } catch (_) {}
  }
}

async function testStartDaemonRejectsOnEarlyExit() {
  console.log('\n## Test: startDaemon rejects when daemon exits before writing state');
  const port = getPort();
  const blocker = http.createServer((req, res) => {
    res.statusCode = 204;
    res.end();
  });

  await new Promise((resolve, reject) => {
    const onError = (err) => {
      blocker.off('listening', onListening);
      reject(err);
    };
    const onListening = () => {
      blocker.off('error', onError);
      resolve();
    };
    blocker.once('error', onError);
    blocker.once('listening', onListening);
    // Bind the wildcard address so daemon.js cannot still claim the port on a
    // different interface family (for example :: vs 127.0.0.1).
    blocker.listen(port);
  });

  let startupError = null;
  try {
    await startDaemon(port);
  } catch (err) {
    startupError = err;
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }

  assert(startupError instanceof Error, 'startDaemon rejects when daemon exits before startup');
  assertIncludes(startupError && startupError.message, 'Daemon exited before startup completed', 'error mentions early daemon exit');
  assertIncludes(startupError && startupError.message, 'EADDRINUSE', 'error surfaces listen failure');
}

async function testResponseShape() {
  console.log('\n## Test: Standard response shape on all routes');
  const port = getPort();
  const { proc, token } = await startDaemon(port);

  try {
    // Success response
    const r1 = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    });
    assert('success' in r1.body, 'Health response has success field');
    assert('data' in r1.body, 'Health response has data field');

    // Error response (401)
    const r2 = await httpRequest({
      hostname: '127.0.0.1', port, path: '/api/health', method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    assertEqual(r2.body.success, false, 'Error response has success=false');
    assert('error' in r2.body, 'Error response has error field');
  } finally {
    await stopDaemon(proc);
  }
}

async function run() {
  console.log('# Browser Daemon Tests — Lifecycle\n');

  const tests = [
    testIdleTimeout,
    testStaleStateCleanup,
    testStartDaemonRejectsOnEarlyExit,
    testResponseShape,
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
