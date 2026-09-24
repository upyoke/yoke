'use strict';

/**
 * Operator sign-in window for one project's persistent browser profile.
 *
 * Usage: node authorize.js --profile-dir path [--url URL]
 *
 * Opens the profile in a plain window of the daemon's own Chromium and blocks
 * until the operator closes it. Whatever they sign into is written into the
 * profile, so every worker context the daemon later opens from it is already
 * signed in. This process never types a credential and never navigates on the
 * operator's behalf beyond the optional starting URL.
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

const { spawn, execFile } = require('child_process');

const WINDOW_POLL_MS = 2000;
const WINDOW_START_MS = 30000;
const AUTHORIZATION_LIMIT_MS = 30 * 60 * 1000;
const SHUTDOWN_MS = 10000;

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

/** Command-line flags for a plain, human-driven browser window. */
function buildLaunchArgs({ profileDir, url }) {
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
  if (url) {
    args.push(url);
  }
  return args;
}

/** The Chromium the daemon drives, so the profile's cookies stay readable. */
function resolveExecutablePath() {
  const executablePath = require('playwright').chromium.executablePath();
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
  const args = { profileDir: '', url: '' };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--profile-dir':
        args.profileDir = argv[++i];
        break;
      case '--url':
        args.url = argv[++i];
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
 * `deps` exists so the contract test can observe the spawn without opening a
 * real browser; production callers pass nothing.
 */
function openSignInWindow(
  { profileDir, url },
  {
    spawnProcess = spawn, executablePath = resolveExecutablePath,
    platform = process.platform, windowCount = macWindowCount,
    pollMs = WINDOW_POLL_MS, startMs = WINDOW_START_MS,
    limitMs = AUTHORIZATION_LIMIT_MS, shutdownMs = SHUTDOWN_MS,
  } = {},
) {
  const binary = executablePath();
  const child = spawnProcess(binary, buildLaunchArgs({ profileDir, url }), {
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
    const stop = (reason) => {
      if (finished || stopping) return;
      stopping = true;
      stoppedBecause = reason;
      child.kill('SIGTERM');
      if (finished) return;
      shutdownTimer = setTimeout(() => finish(new Error(
        `${reason}; spawned Chromium PID ${child.pid} still holds the profile after `
        + `${shutdownMs / 1000}s. Quit that process normally, then rerun `
        + '`yoke browser authorize` without --reset to keep the sign-in.',
      )), shutdownMs);
    };
    const checkWindows = async () => {
      if (finished || stopping) return;
      const elapsed = Date.now() - started;
      if (elapsed >= limitMs) {
        stop(`authorization exceeded ${limitMs / 60000} minutes with Chromium still running`);
        return;
      }
      if (platform === 'darwin') {
        try {
          const count = await windowCount(child.pid);
          if (finished || stopping) return;
          if (count > 0) {
            seenWindow = true;
            emptyChecks = 0;
          } else if (seenWindow && ++emptyChecks >= 2) {
            windowClosed = true;
            stop('all authorization windows closed but Chromium stayed running');
            return;
          } else if (elapsed >= startMs) {
            stop(`Chromium PID ${child.pid} opened no authorization window within ${startMs / 1000}s`);
            return;
          }
        } catch (error) {
          stop(`${error.message}. Close Chromium and check macOS window access`);
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
  console.log('Authorization window closed; Chromium exited.');
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Failed to open the sign-in window: ${err.message}`);
    process.exit(1);
  });
}

module.exports = { buildLaunchArgs, openSignInWindow, resolveExecutablePath };
