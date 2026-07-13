// AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_github_broker.mjs. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
/** Instance-bound bootstrap and external lifecycle management for CI runners. */

import {
  DeleteParameterCommand,
  GetParametersByPathCommand,
  SSMClient,
} from "@aws-sdk/client-ssm";
import {
  deleteRunner,
  listRunners,
  runnerLabels,
  runnerPrefix,
} from "./webapp_runner_github_api.mjs";
import {
  currentAsgInstanceIds,
  currentLifecycleState,
  instanceLaunchTime,
  readRunnerEvents,
  restoreDesiredCapacity,
  writeLifecycleState,
} from "./webapp_runner_aws_state.mjs";
import {
  bootstrapMarkerPrefix,
  bootstrapRunnerHost,
  parseBootstrapMarker,
  registerRunner,
  updateBootstrapState,
} from "./webapp_runner_registration.mjs";
import {
  parseTerminationRecord,
  resumeTermination,
  terminateHost,
} from "./webapp_runner_termination.mjs";

const ssm = new SSMClient({});
const brokerMode = required("BROKER_MODE");
const idleMinutes = positiveInteger(required("IDLE_MINUTES"), "IDLE_MINUTES");
const markerPrefix = bootstrapMarkerPrefix;
const bootstrapTimeout = positiveInteger(
  required("BOOTSTRAP_TIMEOUT_MINUTES"), "BOOTSTRAP_TIMEOUT_MINUTES",
) * 60;
const readyGrace = positiveInteger(
  required("READY_GRACE_MINUTES"), "READY_GRACE_MINUTES",
) * 60;
const maxBootstrapRetries = positiveInteger(
  required("MAX_BOOTSTRAP_RETRIES"), "MAX_BOOTSTRAP_RETRIES",
);
const jobEventTimeout = positiveInteger(
  required("JOB_EVENT_TIMEOUT_MINUTES"), "JOB_EVENT_TIMEOUT_MINUTES",
) * 60;

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function positiveInteger(value, name) {
  if (!/^[1-9]\d*$/.test(value)) throw new Error(`${name} must be positive`);
  return Number(value);
}

function nowSeconds() { return Math.floor(Date.now() / 1000); }

function runnerName(instanceId) { return `${runnerPrefix}${instanceId}`; }

async function loadMarkers(activeIds) {
  const markers = new Map();
  let nextToken;
  for (let pageNumber = 0; pageNumber < 100; pageNumber += 1) {
    const page = await ssm.send(new GetParametersByPathCommand({
      Path: markerPrefix, Recursive: false, NextToken: nextToken,
    }));
    for (const parameter of page.Parameters || []) {
      const name = String(parameter.Name || "");
      const instanceId = name.slice(markerPrefix.length + 1);
      const termination = parseTerminationRecord(parameter.Value);
      if (termination) {
        if (termination.instance_id !== instanceId) {
          throw new Error("runner termination marker instance does not match its path");
        }
        markers.set(instanceId, termination);
      } else if (!activeIds.has(instanceId)) {
        await ssm.send(new DeleteParameterCommand({ Name: name }));
      } else {
        markers.set(instanceId, parseBootstrapMarker(parameter.Value));
      }
    }
    nextToken = page.NextToken;
    if (!nextToken) return markers;
  }
  throw new Error("runner bootstrap marker listing exceeded pagination limit");
}

function matchesFleet(runner) {
  const labels = new Set(
    (runner.labels || []).map((item) => String(item.name || "").toLowerCase()),
  );
  return String(runner.name || "").startsWith(runnerPrefix) &&
    [...runnerLabels].every((label) => labels.has(label));
}

async function retryBootstrap(instanceId, runners, state, activity, reason) {
  const attempts = state.bootstrap_failures + 1;
  const nextState = {
    ...state,
    idle_since: 0,
    bootstrap_failures: attempts,
    online_instance_id: "",
  };
  if (attempts <= maxBootstrapRetries) {
    return terminateHost({
      instanceId, loadRunners: async () => runners, state: nextState,
      activity, reason, decrementDesired: false,
    });
  }
  console.error("runner bootstrap retry budget exhausted", { reason, attempts });
  return terminateHost({
    instanceId, loadRunners: async () => runners, state: nextState,
    activity, reason: "bootstrap_retry_exhausted", decrementDesired: true,
  });
}

async function reapFleet() {
  const activeIds = await currentAsgInstanceIds();
  if (activeIds.size > 1) {
    throw new Error("single-host runner fleet has multiple active instances");
  }
  const markers = await loadMarkers(activeIds);
  const pending = [...markers.entries()].find(([, marker]) =>
    marker.state === "termination_requested" ||
    marker.state === "termination_acknowledged"
  );
  if (pending) {
    const [instanceId, record] = pending;
    return resumeTermination({
      record,
      instanceActive: activeIds.has(instanceId),
      maxAttempts: maxBootstrapRetries,
      loadRunners: async () => (await listRunners())
        .filter(matchesFleet)
        .filter((runner) => runner.name === runnerName(instanceId)),
    });
  }
  const lifecycle = await currentLifecycleState();
  let { state } = lifecycle;
  const { activity } = lifecycle;
  const matching = (await listRunners()).filter(matchesFleet);
  if (!activeIds.size) {
    if (lifecycle.activityChanged) {
      await restoreDesiredCapacity();
      await writeLifecycleState(state);
      return { action: "replaced", reason: "queue_activity_reconciled" };
    }
    if (matching.some((runner) => runner.busy || runner.status === "online")) {
      throw new Error("runner is online without an active fleet instance");
    }
    for (const runner of matching) await deleteRunner(runner.id);
    await writeLifecycleState({ ...state, idle_since: 0 });
    return { action: "kept", reason: "no_instances" };
  }
  if (lifecycle.activityChanged) await writeLifecycleState(state);

  const instanceId = [...activeIds][0];
  const expectedName = runnerName(instanceId);
  const current = matching.filter((runner) => runner.name === expectedName);
  const stale = matching.filter((runner) => runner.name !== expectedName);
  if (stale.some((runner) => runner.busy || runner.status === "online")) {
    throw new Error("stale runner is still active outside the current host");
  }
  for (const runner of stale) await deleteRunner(runner.id);
  if (current.length > 1) throw new Error("multiple runners use the current host name");

  const now = nowSeconds();
  const marker = markers.get(instanceId);
  const launchAge = now - await instanceLaunchTime(instanceId);
  if (!marker) {
    if (launchAge >= bootstrapTimeout) {
      return retryBootstrap(
        instanceId, current, state, activity, "bootstrap_missing",
      );
    }
    await writeLifecycleState({ ...state, idle_since: 0 });
    return { action: "kept", reason: "bootstrap_window" };
  }
  if (marker.state === "failed") {
    return retryBootstrap(
      instanceId, current, state, activity, "bootstrap_failed",
    );
  }
  if (marker.state === "claimed") {
    if (now - marker.at >= bootstrapTimeout) {
      return retryBootstrap(
        instanceId, current, state, activity, "bootstrap_timed_out",
      );
    }
    await writeLifecycleState({ ...state, idle_since: 0 });
    return { action: "kept", reason: "bootstrap_claimed" };
  }

  const runner = current[0];
  const wasOnline = state.online_instance_id === instanceId;
  if (!runner || runner.status !== "online") {
    const { progress, completed } = await readRunnerEvents();
    const completionMatches = completed.action === "completed" &&
      completed.runner_name === expectedName;
    const progressMatches = progress.action === "in_progress" &&
      progress.runner_name === expectedName;
    const currentCycleCompleted = completionMatches &&
      (!progressMatches || progress.job_id === completed.job_id);
    if (currentCycleCompleted && now - completed.at < readyGrace) {
      await writeLifecycleState({
        ...state, idle_since: 0, online_instance_id: instanceId,
      });
      return { action: "kept", reason: "runner_rearm_window" };
    }
    if (!currentCycleCompleted && now - marker.at < readyGrace) {
      await writeLifecycleState({ ...state, idle_since: 0 });
      return { action: "kept", reason: "runner_startup_window" };
    }
    if (!currentCycleCompleted && progressMatches &&
        now - progress.at < jobEventTimeout) {
      await writeLifecycleState({
        ...state, idle_since: 0, online_instance_id: instanceId,
      });
      return { action: "kept", reason: "job_event_in_progress" };
    }
    if (!currentCycleCompleted && !wasOnline) {
      return retryBootstrap(
        instanceId, current, state, activity, "runner_never_online",
      );
    }
    return retryBootstrap(
      instanceId, current, state, activity, "runner_rearm_failed",
    );
  }
  state = {
    ...state, bootstrap_failures: 0, online_instance_id: instanceId,
  };
  if (runner.busy) {
    await writeLifecycleState({ ...state, idle_since: 0 });
    return { action: "kept", reason: "busy" };
  }
  if (!state.idle_since || now - state.idle_since < idleMinutes * 60) {
    if (!state.idle_since) {
      state = { ...state, idle_since: now };
    }
    await writeLifecycleState(state);
    return { action: "kept", reason: "idle_window" };
  }
  return terminateHost({
    instanceId, loadRunners: async () => current, state, activity,
    reason: "idle", decrementDesired: true,
  });
}

export async function handler(event) {
  const action = event && typeof event === "object" ? event.action : "";
  if (brokerMode === "bootstrap") {
    if (action === "bootstrap") return bootstrapRunnerHost(event.instance_id);
    if (action === "register") return registerRunner(event.instance_id);
    if (action === "ready") {
      return updateBootstrapState(event.instance_id, "ready");
    }
    if (action === "failed") {
      return updateBootstrapState(event.instance_id, "failed");
    }
  } else if (brokerMode === "reaper" && action === "reap") {
    return reapFleet();
  }
  throw new Error("unsupported runner broker action");
}
