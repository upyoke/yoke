'use strict';

/**
 * Which Linux processes can own the sign-in window.
 *
 * The PID Node spawns is often a launcher (/usr/bin/chromium-browser,
 * /snap/bin/chromium) whose child is the real browser, and X11 stamps each
 * window's _NET_WM_PID with that child. So the window check looks at every
 * Chromium main process -- no `--type=` switch, like
 * linux_chromium_processes.browser_pids -- that is the spawned PID, one of its
 * descendants, or running this profile.
 */

const fs = require('fs');
const path = require('path');

function readProcess(procRoot, pid) {
  const dir = path.join(procRoot, pid);
  try {
    const stat = fs.readFileSync(path.join(dir, 'stat'), 'utf8');
    // comm may hold spaces or parentheses; ppid is the second field after it.
    const ppid = Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[1]);
    // Chromium's process title can flatten all argv into one NUL field, so
    // match switches against the command line with NULs read as spaces.
    const cmdline = ` ${fs.readFileSync(path.join(dir, 'cmdline'), 'utf8').replace(/\0/g, ' ')} `;
    return { pid: Number(pid), ppid, uid: fs.statSync(dir).uid, cmdline };
  } catch {
    return null; // the process exited while we read it
  }
}

function windowOwnerPids(rootPid, profileDir, { procRoot = '/proc', uid = process.getuid() } = {}) {
  const processes = fs.readdirSync(procRoot)
    .filter((name) => /^\d+$/.test(name))
    .map((name) => readProcess(procRoot, name))
    .filter((proc) => proc && proc.uid === uid);
  const tree = new Set([rootPid]);
  for (let grew = true; grew;) {
    grew = false;
    for (const proc of processes) {
      if (!tree.has(proc.pid) && tree.has(proc.ppid)) {
        tree.add(proc.pid);
        grew = true;
      }
    }
  }
  const profileArg = ` --user-data-dir=${profileDir} `;
  const owners = new Set([rootPid]);
  for (const proc of processes) {
    if (proc.cmdline.includes(' --type=')) continue;
    if (tree.has(proc.pid) || proc.cmdline.includes(profileArg)) owners.add(proc.pid);
  }
  return [...owners];
}

module.exports = { windowOwnerPids };
