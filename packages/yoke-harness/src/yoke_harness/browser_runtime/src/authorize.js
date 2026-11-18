'use strict';

/**
 * Operator sign-in window for one project's persistent browser profile.
 *
 * Usage: node authorize.js --profile-dir path [--url URL ...]
 *
 * Opens the profile in a plain window of the daemon's own Chromium and blocks
 * until the operator closes it. Whatever they sign into is written into the
 * profile, so every worker context the daemon later opens from it is already
 * signed in. This process never types a credential and never navigates on the
 * operator's behalf beyond the optional starting URLs, one tab each -- the
 * sites whose sign-in has expired when the caller names them.
 *
 * The window is a directly spawned browser process, not a Playwright context.
 * Playwright's launchPersistentContext runs the browser under automation
 * control -- `--enable-automation`, `navigator.webdriver`, an attached CDP
 * session -- and Google's sign-in refuses exactly that shape with "Couldn't
 * sign you in. This browser or app may not be secure", which made the profile
 * impossible to sign into through Google. Spawning the executable plainly is
 * the fix; do not reintroduce a Playwright context here, and do not try to
 * mask the automation signals instead.
 *
 * It has to be the SAME binary the daemon drives, launched with the SAME
 * cookie-encryption switches. Chromium encrypts every stored cookie against a
 * key it takes from the platform credential store, and drops any cookie it
 * cannot decrypt when it loads the profile. Playwright always launches with
 * `--password-store=basic --use-mock-keychain`, which puts its Chromium in a
 * different key domain from a default launch, so a window opened without them
 * wrote cookies the daemon then discarded -- the whole sign-in, including
 * cookies that carried an explicit expiry. Passing the same two switches here
 * is what makes the operator's sign-in readable afterwards.
 */

const fs = require('fs');
const path = require('path');
const { spawn, execFile } = require('child_process');
const { windowOwnerPids } = require('./linux-window-owners');
const { profileLockOwner, quitProfileOwner, signalProcess } = require('./profile-lock');

const WINDOW_POLL_MS = 2000;
const WINDOW_START_MS = 30000;
const { AUTHORIZATION_LIMIT_MS, SHUTDOWN_MS } = require('./authorization-limits.json');

// CoreGraphics counts every window, including minimized and off-screen ones.
// The query only reads window metadata for our spawned PID; it does not attach
// to Chromium or automate the sign-in page.
const MAC_WINDOW_QUERY = `
ObjC.import('CoreGraphics');
function run(argv) {
  const pid = Number(argv[0]);
  const windows = $.CGWindowListCopyWindowInfo($.kCGWindowListOptionAll, $.kCGNullWindowID);
  let count = 0;
  for (let i = 0; i < $.CFArrayGetCount(windows); i++) {
    const info = ObjC.castRefToObject($.CFArrayGetValueAtIndex(windows, i));
    if (ObjC.unwrap(info.objectForKey($('kCGWindowOwnerPID'))) === pid
        && ObjC.unwrap(info.objectForKey($('kCGWindowLayer'))) === 0) count++;
  }
  return count;
}`;

function macWindowCount(pid) {
  return new Promise((resolve, reject) => {
    execFile('osascript', ['-l', 'JavaScript', '-e', MAC_WINDOW_QUERY, String(pid)],
      { timeout: 5000 }, (error, stdout, stderr) => {
        if (error) {
          reject(new Error(`macOS window check failed: ${stderr.trim() || error.message}`));
          return;
        }
        const count = Number(stdout.trim());
        if (!Number.isInteger(count) || count < 0) {
          reject(new Error(`macOS window check returned ${JSON.stringify(stdout.trim())}`));
          return;
        }
        resolve(count);
      });
  });
}

function xdotoolWindows(pid) {
  return new Promise((resolve, reject) => {
    execFile('xdotool', ['search', '--pid', String(pid)], { timeout: 5000 },
      (error, stdout, stderr) => {
        if (error && error.code !== 1) {
          reject(new Error(`linux_authorization_window_check_failed: ${stderr.trim() || error.message}; install xdotool and check DISPLAY`));
          return;
        }
        resolve(stdout.trim() ? stdout.trim().split(/\s+/) : []);
      });
  });
}

// X11 stamps a window with the PID of the browser that drew it, and the PID we
// spawned may be a launcher whose child is that browser, so count the windows
// of every Chromium main process in the spawned tree or on this profile.
async function linuxWindowCount(pid, profileDir, {
  ownerPids = windowOwnerPids, searchWindows = xdotoolWindows,
} = {}) {
  const windows = new Set();
  for (const owner of ownerPids(pid, profileDir)) {
    for (const id of await searchWindows(owner)) windows.add(id);
  }
  return windows.size;
}

/** Command-line flags for a plain, human-driven browser window. */
function buildLaunchArgs({ profileDir, urls = [] }) {
  const args = [
    `--user-data-dir=${profileDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-mode',
    // The daemon's Playwright launch always passes these two, and a cookie
    // written under one key domain is unreadable -- so silently dropped --
    // under the other. Keep them identical on both sides.
    '--password-store=basic',
    '--use-mock-keychain',
  ];
  args.push(...urls);
  return args;
}

/**
 * Drop the tabs a previous window left behind, keeping the sign-in.
 *
 * Every Yoke shutdown of this window is a SIGTERM, which Chromium records as
 * a session end (`exit_type` SessionEnded) and answers on the next launch by
 * restoring that session's tabs next to the new starting URLs -- one more
 * copy of the same site on every run. The saved session lives only in
 * `Default/Sessions`; cookies and the rest of the profile stay untouched.
 */
function discardSavedSession(profileDir) {
  fs.rmSync(path.join(profileDir, 'Default', 'Sessions'), { recursive: true, force: true });
}

/** The Chromium the daemon drives, so the profile's cookies stay readable. */
function resolveExecutablePath() {
  const executablePath = require('./browser-executable').executablePath()
    || require('playwright').chromium.executablePath();
  if (!executablePath) {
    throw new Error(
      'Playwright reported no Chromium executable. Run '
      + '`npx --no-install playwright install chromium` in the browser '
      + 'runtime directory, then retry.',
    );
  }
  return executablePath;
}

function parseArgs(argv) {
  const args = { profileDir: '', urls: [] };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--profile-dir':
        args.profileDir = argv[++i];
        break;
      case '--url':
        args.urls.push(argv[++i]);
        break;
      default:
        console.error(`Unknown argument: ${argv[i]}`);
        process.exit(3);
    }
  }
  if (!args.profileDir) {
    console.error('--profile-dir is required.');
    process.exit(3);
  }
  return args;
}

/**
 * Spawn the sign-in window and resolve once the operator closes it.
 *
 * A browser still holding the profile is quit first: otherwise Chromium's
 * single-instance lock forwards the URLs to it as extra tabs and the new
 * launch exits 0 at once (see profile-lock.js). Its saved session is then
 * discarded, so the window opens only the starting URLs.
 *
 * `deps` exists so the contract test can observe the spawn without opening a
 * real browser; production callers pass nothing.
 */
async function openSignInWindow(
  { profileDir, urls },
  {
    spawnProcess = spawn, executablePath = resolveExecutablePath,
    platform = process.platform, windowCount,
    pollMs = WINDOW_POLL_MS, startMs = WINDOW_START_MS,
    limitMs = AUTHORIZATION_LIMIT_MS, shutdownMs = SHUTDOWN_MS,
  } = {},
) {
  windowCount ??= platform === 'linux' ? linuxWindowCount : macWindowCount;
  const binary = executablePath();
  const holder = profileLockOwner(profileDir);
  if (holder !== null) await quitProfileOwner(holder, profileDir, { shutdownMs });
  discardSavedSession(profileDir);
  const child = spawnProcess(binary, buildLaunchArgs({ profileDir, urls }), {
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let stderr = '';
  if (child.stderr) {
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  }
  return new Promise((resolve, reject) => {
    let finished = false;
    let seenWindow = false;
    let emptyChecks = 0;
    let windowClosed = false;
    let stopping = false;
    let stoppedBecause = '';
    let timer;
    let shutdownTimer;
    const started = Date.now();
    const finish = (error) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      clearTimeout(shutdownTimer);
      if (error) reject(error);
      else resolve();
    };
    const stop = (reason, forceOnTimeout = false) => {
      if (finished || stopping) return;
      stopping = true;
      stoppedBecause = reason;
      // The spawned PID may be a launcher whose child is the real browser,
      // and that browser holds the profile lock, so signal both.
      let owner = null;
      try {
        owner = profileLockOwner(profileDir);
      } catch (error) {
        stoppedBecause = `${reason}; ${error.message}`;
      }
      if (owner === child.pid) owner = null;
      const signal = (name) => {
        child.kill(name);
        // A refused signal leaves the owner running; the shutdown timeout
        // then names its PID.
        if (owner !== null) {
          try { signalProcess(owner, name); } catch { /* reported by the timeout */ }
        }
      };
      signal('SIGTERM');
      if (finished) return;
      shutdownTimer = setTimeout(() => {
        if (forceOnTimeout) signal('SIGKILL');
        finish(new Error(
          forceOnTimeout
            ? `${reason}; Chromium was force-stopped. Reopen with `
              + '`yoke browser authorize` without --reset to keep the sign-in.'
            : `${reason}; Chromium PID ${owner ?? child.pid} still holds the profile after `
              + `${shutdownMs / 1000}s. Quit that process normally, then rerun `
              + '`yoke browser authorize` without --reset to keep the sign-in.',
        ));
      }, shutdownMs);
    };
    const checkWindows = async () => {
      if (finished || stopping) return;
      const elapsed = Date.now() - started;
      if (elapsed >= limitMs) {
        stop(`authorization exceeded ${limitMs / 60000} minutes with Chromium still running`, true);
        return;
      }
      if (platform === 'darwin' || platform === 'linux') {
        try {
          const count = await windowCount(child.pid, profileDir);
          if (finished || stopping) return;
          if (count > 0) {
            seenWindow = true;
            emptyChecks = 0;
          } else if (seenWindow) {
            // One empty check is a window between maps; two in a row is closed.
            if (++emptyChecks >= 2) {
              windowClosed = true;
              stop('all authorization windows closed but Chromium stayed running');
              return;
            }
          } else if (elapsed >= startMs) {
            stop(`Chromium PID ${child.pid} opened no authorization window within ${startMs / 1000}s`);
            return;
          }
        } catch (error) {
          stop(`${error.message}. Close Chromium and check ${platform} window access`);
          return;
        }
      }
      timer = setTimeout(checkWindows, pollMs);
    };
    child.on('error', (err) => finish(new Error(
      `could not start ${binary}: ${err.message}. Run `
      + '`yoke qa browser status` to check the browser runtime, then retry.',
    )));
    child.on('exit', (code, signal) => {
      if ((!stopping && code === 0)
          || (windowClosed && (code === 0 || signal === 'SIGTERM'))) {
        finish();
        return;
      }
      const tail = stderr.trim().split('\n').slice(-5).join('\n');
      finish(new Error(
        (stoppedBecause || `the browser exited with status ${code ?? signal}`)
        + '. Reopen it with `yoke browser authorize` without --reset.'
        + (tail ? `\n${tail}` : ''),
      ));
    });
    timer = setTimeout(checkWindows, pollMs);
  });
}

async function main() {
  const args = parseArgs(process.argv);
  console.log('Sign in to whatever sites you need, then close the window.');
  await openSignInWindow(args);
  console.log('Authorization window closed; verifying sign-in.');
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Failed to open the sign-in window: ${err.message}`);
    process.exit(1);
  });
}

module.exports = {
  buildLaunchArgs, linuxWindowCount, openSignInWindow, resolveExecutablePath,
};
