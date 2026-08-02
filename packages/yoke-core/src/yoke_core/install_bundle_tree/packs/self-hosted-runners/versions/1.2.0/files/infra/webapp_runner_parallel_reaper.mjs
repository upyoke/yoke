/** Independent lifecycle reconciliation for a bounded parallel host pool. */

import { deleteRunner } from "./webapp_runner_github_api.mjs";
import {
  instanceLaunchTime,
  readRunnerEvents,
  writeLifecycleState,
} from "./webapp_runner_aws_state.mjs";
import { terminateHost } from "./webapp_runner_termination.mjs";

function instanceIdForRunner(runner, runnerPrefix) {
  const name = String(runner.name || "");
  const instanceId = name.startsWith(runnerPrefix)
    ? name.slice(runnerPrefix.length) : "";
  return /^i-[0-9a-f]{8,17}$/.test(instanceId) ? instanceId : "";
}

function recentRunnerTransition(
  events, expectedName, now, readyGrace, jobEventTimeout,
) {
  const { progress, completed } = events;
  const completionMatches = completed.action === "completed" &&
    completed.runner_name === expectedName && now - completed.at < readyGrace;
  const progressMatches = progress.action === "in_progress" &&
    progress.runner_name === expectedName && now - progress.at < jobEventTimeout;
  return completionMatches || progressMatches;
}

export async function reapParallelFleet({
  activeIds,
  markers,
  lifecycle,
  matching,
  runnerPrefix,
  readyGrace,
  jobEventTimeout,
  bootstrapTimeout,
  idleSeconds,
  retryBootstrap,
}) {
  let { state } = lifecycle;
  const { activity } = lifecycle;
  if (lifecycle.activityChanged) await writeLifecycleState(state);

  const byInstance = new Map([...activeIds].map((instanceId) => [instanceId, []]));
  const stale = [];
  for (const runner of matching) {
    const instanceId = instanceIdForRunner(runner, runnerPrefix);
    if (byInstance.has(instanceId)) byInstance.get(instanceId).push(runner);
    else stale.push(runner);
  }
  if (stale.some((runner) => runner.busy || runner.status === "online")) {
    throw new Error("stale runner is still active outside the current hosts");
  }
  for (const runner of stale) await deleteRunner(runner.id);

  const now = Math.floor(Date.now() / 1000);
  let allOnline = true;
  let anyBusy = false;
  const idleHosts = new Set();
  let events;
  for (const instanceId of [...activeIds].sort()) {
    const current = byInstance.get(instanceId);
    if (current.length > 1) {
      throw new Error("multiple runners use the same fleet host name");
    }
    const marker = markers.get(instanceId);
    const launchAge = now - await instanceLaunchTime(instanceId);
    if (!marker) {
      allOnline = false;
      if (launchAge >= bootstrapTimeout) {
        return retryBootstrap(
          instanceId, current, state, activity, "bootstrap_missing",
        );
      }
      continue;
    }
    if (marker.state === "failed") {
      return retryBootstrap(
        instanceId, current, state, activity, "bootstrap_failed",
      );
    }
    if (marker.state === "claimed") {
      allOnline = false;
      if (now - marker.at >= bootstrapTimeout) {
        return retryBootstrap(
          instanceId, current, state, activity, "bootstrap_timed_out",
        );
      }
      continue;
    }

    const runner = current[0];
    if (runner && runner.status === "online") {
      anyBusy ||= Boolean(runner.busy);
      if (!runner.busy) idleHosts.add(instanceId);
      continue;
    }
    allOnline = false;
    if (now - marker.at < readyGrace) continue;
    events ||= await readRunnerEvents();
    if (recentRunnerTransition(
      events, `${runnerPrefix}${instanceId}`, now, readyGrace, jobEventTimeout,
    )) continue;
    return retryBootstrap(
      instanceId, current, state, activity, "runner_rearm_failed",
    );
  }

  // Every host keeps its own idle clock. A single fleet-wide clock meant one
  // busy or still-booting host reset the timer for every other host, so an
  // idle host only ever retired if the whole pool fell quiet together — which
  // during a working day it never does. Hosts then outlived the idle window
  // by hours while doing nothing.
  //
  // A host is marked idle only while it is online and unclaimed; going busy,
  // dropping offline, or leaving the pool drops its mark by omission, which
  // also keeps the map from growing without bound.
  // A host with no mark of its own inherits the old fleet-wide clock when one
  // is set. That clock was only ever left running while every host was idle,
  // so it is a sound lower bound for each of them, and inheriting it means the
  // first pass after this change keeps the idle time already accumulated
  // instead of restarting every host's window from zero.
  const previousIdle = state.idle_by_instance || {};
  const idleByInstance = {};
  for (const instanceId of idleHosts) {
    idleByInstance[instanceId] =
      previousIdle[instanceId] || state.idle_since || now;
  }
  state = {
    ...state,
    bootstrap_failures: allOnline ? 0 : state.bootstrap_failures,
    online_instance_id: "",
    idle_by_instance: idleByInstance,
    // The single-host path still reads this; clear it so that path starts a
    // fresh window if the pool later shrinks to one host, rather than acting
    // on a timestamp this path stopped maintaining.
    idle_since: 0,
  };

  // Retire the host idle longest, one per pass: the reaper runs every minute,
  // so a fully idle pool still drains within minutes, and terminating one at a
  // time leaves capacity for work that arrives mid-drain.
  const reapable = [...idleHosts]
    .filter((instanceId) => now - idleByInstance[instanceId] >= idleSeconds)
    .sort((a, b) => idleByInstance[a] - idleByInstance[b]);
  if (!reapable.length) {
    await writeLifecycleState(state);
    let reason = "idle_window";
    if (anyBusy) reason = "busy";
    else if (!allOnline) reason = "host_transition";
    return { action: "kept", reason };
  }

  const instanceId = reapable[0];
  const current = byInstance.get(instanceId);
  return terminateHost({
    instanceId, loadRunners: async () => current, state, activity,
    reason: "idle", decrementDesired: true,
  });
}
