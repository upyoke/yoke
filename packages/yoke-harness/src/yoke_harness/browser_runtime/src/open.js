'use strict';

/**
 * Open a URL in a visible window of one identity's live browser profile.
 *
 * Usage: node open.js --profile-dir path --url URL
 *
 * The window is the same plain Chromium the sign-in window spawns
 * (authorize.js: same binary, same cookie-encryption switches), so it reads
 * the identity's sign-in. It also listens on a loopback DevTools port, which
 * Chromium records in the profile's DevToolsActivePort file; Yoke's approval
 * driver reads that file to find the page. One Chromium process holds a
 * profile: when it is already running, Chromium hands the URL to that
 * process, which opens a visible tab, and the new process exits.
 *
 * The browser outlives this script. The script reports once the window's
 * DevTools port answers or the running browser took the URL.
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { buildLaunchArgs, resolveExecutablePath } = require('./authorize');

const READY_MS = 20000;
const POLL_MS = 250;
const PORT_FILE = 'DevToolsActivePort';

function devtoolsPort(profileDir, notBefore = 0) {
  try {
    const file = path.join(profileDir, PORT_FILE);
    if (fs.statSync(file).mtimeMs < notBefore) return null;
    const port = Number(fs.readFileSync(file, 'utf8').split('\n')[0]);
    return Number.isInteger(port) && port > 0 ? port : null;
  } catch {
    return null;
  }
}

function launchArgs({ profileDir, url }) {
  return [...buildLaunchArgs({ profileDir }), '--remote-debugging-port=0', url];
}

/** Resolve with how the URL was opened; reject naming why it was not. */
function openIdentityWindow(
  { profileDir, url },
  {
    spawnProcess = spawn, executablePath = resolveExecutablePath,
    readyMs = READY_MS, pollMs = POLL_MS, now = Date.now,
  } = {},
) {
  const binary = executablePath();
  const started = now() - 1000;
  const child = spawnProcess(binary, launchArgs({ profileDir, url }), {
    detached: true,
    stdio: 'ignore',
  });
  return new Promise((resolve, reject) => {
    let finished = false;
    let timer;
    const finish = (error, result) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (typeof child.unref === 'function') child.unref();
      if (error) reject(error);
      else resolve(result);
    };
    child.on('error', (err) => finish(new Error(
      `browser_open_failed: could not start ${binary}: ${err.message}. Run `
      + '`yoke qa browser status` to check the browser runtime, then retry.',
    )));
    child.on('exit', (code, signal) => {
      if (code === 0) {
        finish(null, { opened: 'running_browser', devtools_port: devtoolsPort(profileDir) });
        return;
      }
      finish(new Error(
        `browser_open_failed: Chromium exited with status ${code ?? signal} before `
        + 'opening the page. Close any other window using this identity, run '
        + '`yoke qa browser status`, then retry.',
      ));
    });
    const poll = () => {
      if (finished) return;
      const port = devtoolsPort(profileDir, started);
      if (port !== null) {
        finish(null, { opened: 'new_window', devtools_port: port, pid: child.pid });
        return;
      }
      if (now() - started >= readyMs) {
        finish(new Error(
          `browser_open_not_ready: Chromium PID ${child.pid} wrote no ${PORT_FILE} `
          + `in ${profileDir} within ${readyMs / 1000}s. Check the desktop session `
          + 'and `yoke qa browser status`, then retry.',
        ));
        return;
      }
      timer = setTimeout(poll, pollMs);
    };
    timer = setTimeout(poll, pollMs);
  });
}

function parseArgs(argv) {
  const args = { profileDir: '', url: '' };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--profile-dir') args.profileDir = argv[++i];
    else if (argv[i] === '--url') args.url = argv[++i];
    else {
      console.error(`Unknown argument: ${argv[i]}`);
      process.exit(3);
    }
  }
  if (!args.profileDir || !args.url) {
    console.error('--profile-dir and --url are required.');
    process.exit(3);
  }
  return args;
}

if (require.main === module) {
  openIdentityWindow(parseArgs(process.argv)).then(
    (result) => { console.log(JSON.stringify({ ok: true, ...result })); process.exit(0); },
    (error) => { console.log(JSON.stringify({ ok: false, error: error.message })); process.exit(1); },
  );
}

module.exports = { devtoolsPort, launchArgs, openIdentityWindow };
