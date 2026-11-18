'use strict';

/**
 * The Chromium that holds a browser profile, read from its SingletonLock.
 *
 * On Linux and macOS Chromium marks a profile in use with
 * `<profile>/SingletonLock`, a symlink to `<hostname>-<pid>` of the browser
 * main process. A second launch on that profile does not open its own window:
 * it forwards its URLs to the holder as new tabs and exits 0. So a Chromium
 * left over from an earlier sign-in run -- a launcher's child that survived
 * the launcher's SIGTERM, or a browser whose node parent was killed -- turns
 * the next run into an extra tab in the old window, and its exit 0 reads as
 * the operator closing the window.
 *
 * A lock only counts when it names this host and a live process whose
 * command line runs this profile; anything else is stale (a reboot, another
 * machine on a shared home), and quitting a reused PID would hit an unrelated
 * program.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

function lockTarget(profileDir) {
  const lock = path.join(profileDir, 'SingletonLock');
  try {
    return fs.readlinkSync(lock);
  } catch (error) {
    if (['ENOENT', 'ENOTDIR', 'EINVAL'].includes(error.code)) return '';
    throw new Error(`could not read ${lock}: ${error.message}; check the profile's permissions, then rerun`);
  }
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function runsProfile(pid, profileDir) {
  let args;
  try {
    // -ww: never cut the command line to a terminal width.
    args = execFileSync('ps', ['-ww', '-o', 'args=', '-p', String(pid)], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
    });
  } catch {
    return false; // ps exits non-zero once the process is gone
  }
  return ` ${args.trim()} `.includes(` --user-data-dir=${profileDir} `);
}

/** PID of the live local browser holding `profileDir`, or null. */
function profileLockOwner(profileDir, { hostname = os.hostname() } = {}) {
  const match = /^(.*)-(\d+)$/.exec(lockTarget(profileDir));
  if (!match || match[1] !== hostname) return null;
  const pid = Number(match[2]);
  return isAlive(pid) && runsProfile(pid, profileDir) ? pid : null;
}

function signalProcess(pid, signal) {
  try {
    process.kill(pid, signal);
    return true;
  } catch (error) {
    if (error.code === 'ESRCH') return false;
    throw error;
  }
}

/**
 * Ask the profile's holder to quit and wait for it to exit, so the next
 * launch opens its own window instead of forwarding to it. Chromium records
 * a SIGTERM as a session end and restores that session's tabs on the next
 * launch; authorize.js discards the saved session before it spawns.
 */
async function quitProfileOwner(pid, profileDir, { shutdownMs, pollMs = 100 }) {
  const refusal = (detail) => new Error(
    `authorization_profile_in_use: PID ${pid} still holds ${profileDir}${detail}; quit it, then rerun`,
  );
  try {
    signalProcess(pid, 'SIGTERM');
  } catch (error) {
    throw refusal(` (${error.code || error.message})`);
  }
  const deadline = Date.now() + shutdownMs;
  while (isAlive(pid)) {
    if (Date.now() >= deadline) throw refusal('');
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}

module.exports = { profileLockOwner, quitProfileOwner, signalProcess };
