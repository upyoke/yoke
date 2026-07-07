'use strict';

/**
 * Browser daemon -- CLI entry point.
 *
 * Usage: node daemon.js [--port N] [--headed] [--idle-timeout N] [--state-file path]
 *
 * Starts an Express server, launches Chromium via Playwright, writes a state file,
 * and manages idle shutdown and graceful stop.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { createBrowserManager } = require('./browser-manager');
const { createServer } = require('./server');
const registerSnapshotRoutes = require('./routes/snapshot-routes');
const registerExecRoutes = require('./routes/exec-routes');

// ---------------------------------------------------------------------------
// Arg parsing
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = {
    port: 9222,
    headed: false,
    idleTimeoutMs: 10 * 60 * 1000, // 10 minutes
    stateFile: path.join(__dirname, '..', '.daemon-state.json'),
  };

  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--port':
        args.port = parseInt(argv[++i], 10);
        break;
      case '--headed':
        args.headed = true;
        break;
      case '--headless':
        // explicit headless (default) -- no-op
        break;
      case '--idle-timeout':
        args.idleTimeoutMs = parseInt(argv[++i], 10);
        break;
      case '--state-file':
        args.stateFile = argv[++i];
        break;
      default:
        console.error(`Unknown argument: ${argv[i]}`);
        process.exit(3);
    }
  }
  return args;
}

// ---------------------------------------------------------------------------
// State file management
// ---------------------------------------------------------------------------

function writeStateFile(filePath, state) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(filePath, JSON.stringify(state, null, 2), { mode: 0o600 });
}

function readStateFile(filePath) {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return null;
  }
}

function removeStateFile(filePath) {
  try {
    fs.unlinkSync(filePath);
  } catch (_) {
    // May already be gone
  }
}

/**
 * Check if a PID is alive.
 */
function isPidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Handle stale state file from a previous crash.
 */
function handleStaleState(stateFile) {
  const existing = readStateFile(stateFile);
  if (!existing) return;

  if (existing.pid && isPidAlive(existing.pid)) {
    console.error(`Daemon already running (PID ${existing.pid}). Stop it first.`);
    process.exit(1);
  }

  // Stale state file from a crashed daemon -- clean up
  console.log(`Cleaning up stale state file (PID ${existing.pid} no longer running)`);
  removeStateFile(stateFile);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv);

  // AC-9: Handle stale state file
  handleStaleState(args.stateFile);

  const token = crypto.randomBytes(24).toString('hex');
  const browserManager = createBrowserManager({
    browserType: 'chromium',
    headless: !args.headed,
  });

  // Launch the browser
  console.log(`Launching Chromium (${args.headed ? 'headed' : 'headless'})...`);
  await browserManager.launch();
  console.log('Browser launched.');

  // Idle timer
  let idleTimer = null;

  function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    if (args.idleTimeoutMs > 0) {
      idleTimer = setTimeout(async () => {
        console.log('Idle timeout reached. Shutting down.');
        await shutdown(false);
      }, args.idleTimeoutMs);
      // Don't keep the process alive just for the timer
      if (idleTimer.unref) idleTimer.unref();
    }
  }

  let server = null;
  let isShuttingDown = false;

  async function shutdown(cleanExit = true) {
    if (isShuttingDown) return;
    isShuttingDown = true;

    if (idleTimer) clearTimeout(idleTimer);
    console.log('Shutting down...');

    await browserManager.closeBrowser();

    if (server) {
      await new Promise((resolve) => server.close(resolve));
    }

    // AC-6/AC-7: Remove state file on clean shutdown
    removeStateFile(args.stateFile);
    console.log('Shutdown complete.');

    if (cleanExit) {
      process.exit(0);
    }
  }

  // Create Express app
  const app = createServer({
    port: args.port,
    token,
    browserManager,
    stateFilePath: args.stateFile,
    idleTimeoutMs: args.idleTimeoutMs,
    onActivity: resetIdleTimer,
    onStop: () => shutdown(true),
  });

  // Register route modules (GAP #3 pattern: each module is (app, browserManager) => void)
  registerSnapshotRoutes(app, browserManager);
  registerExecRoutes(app, browserManager);

  // Start server
  server = app.listen(args.port, () => {
    const endpoint = `http://127.0.0.1:${args.port}`;

    // AC-2: Write state file
    const state = {
      pid: process.pid,
      token,
      endpoint,
      browserType: 'chromium',
      startedAt: new Date().toISOString(),
      health: 'healthy',
      port: args.port,
    };

    writeStateFile(args.stateFile, state);
    console.log(`Daemon listening on ${endpoint}`);
    console.log(`State file: ${args.stateFile}`);

    // Start idle timer
    resetIdleTimer();
  });

  // Handle signals for graceful shutdown
  process.on('SIGTERM', () => shutdown(true));
  process.on('SIGINT', () => shutdown(true));

  // AC-8: On uncaught exception, mark state as crashed (leave state file)
  process.on('uncaughtException', (err) => {
    console.error('Uncaught exception:', err);
    const existing = readStateFile(args.stateFile);
    if (existing) {
      existing.health = 'crashed';
      writeStateFile(args.stateFile, existing);
    }
    process.exit(1);
  });
}

main().catch((err) => {
  console.error('Failed to start daemon:', err);
  process.exit(1);
});
