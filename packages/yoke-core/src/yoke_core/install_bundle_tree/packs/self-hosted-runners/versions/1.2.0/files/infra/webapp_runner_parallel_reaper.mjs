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

  state = {
    ...state,
    bootstrap_failures: allOnline ? 0 : state.bootstrap_failures,
    online_instance_id: "",
  };
  if (anyBusy || !allOnline) {
    await writeLifecycleState({ ...state, idle_since: 0 });
    return {
      action: "kept", reason: anyBusy ? "busy" : "host_transition",
    };
  }
  if (!state.idle_since || now - state.idle_since < idleSeconds) {
    if (!state.idle_since) state = { ...state, idle_since: now };
    await writeLifecycleState(state);
    return { action: "kept", reason: "idle_window" };
  }

  const instanceId = [...activeIds].sort()[0];
  const current = byInstance.get(instanceId);
  return terminateHost({
    instanceId, loadRunners: async () => current, state, activity,
    reason: "idle", decrementDesired: true,
  });
}
