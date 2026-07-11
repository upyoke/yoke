// AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_github_broker.mjs. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
/** Instance-bound bootstrap and external lifecycle management for CI runners. */

import {
  DeleteParameterCommand,
  GetParameterCommand,
  GetParametersByPathCommand,
  PutParameterCommand,
  SSMClient,
} from "@aws-sdk/client-ssm";
import {
  deleteRunner,
  listRunners,
  registrationToken,
  runnerDownloadUrl,
  runnerLabels,
  runnerPrefix,
} from "./webapp_runner_github_api.mjs";
import {
  assertActiveInstance,
  currentAsgInstanceIds,
  currentLifecycleState,
  instanceLaunchTime,
  readRunnerEvents,
  restoreDesiredCapacity,
  writeLifecycleState,
} from "./webapp_runner_aws_state.mjs";
import {
  parseTerminationRecord,
  resumeTermination,
  terminateHost,
} from "./webapp_runner_termination.mjs";

const ssm = new SSMClient({});
const brokerMode = required("BROKER_MODE");
const idleMinutes = positiveInteger(required("IDLE_MINUTES"), "IDLE_MINUTES");
const markerPrefix = required("BOOTSTRAP_MARKER_PREFIX").replace(/\/$/, "");
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

function validateInstanceId(value) {
  const instanceId = String(value || "");
  if (!/^i-[0-9a-f]{8,17}$/.test(instanceId)) {
    throw new Error("instance_id must be an EC2 instance id");
  }
  return instanceId;
}

function markerName(instanceId) { return `${markerPrefix}/${instanceId}`; }

function runnerName(instanceId) { return `${runnerPrefix}${instanceId}`; }

function markerValue(state, at = nowSeconds()) {
  return JSON.stringify({ state, at });
}

function parseMarker(value) {
  try {
    const parsed = JSON.parse(String(value || ""));
    if (!["claimed", "ready", "failed"].includes(parsed.state) ||
        !Number.isSafeInteger(parsed.at) || parsed.at <= 0) {
      throw new Error("invalid marker fields");
    }
    return parsed;
  } catch (_error) {
    throw new Error("runner bootstrap marker is malformed");
  }
}

async function claimBootstrap(instanceId) {
  await assertActiveInstance(instanceId);
  const name = markerName(instanceId);
  try {
    await ssm.send(new PutParameterCommand({
      Name: name, Type: "String", Value: markerValue("claimed"), Overwrite: false,
    }));
  } catch (error) {
    if (error && error.name === "ParameterAlreadyExists") {
      throw new Error("runner bootstrap was already consumed for this instance");
    }
    throw error;
  }
  return name;
}

async function updateBootstrapState(instanceId, state) {
  await assertActiveInstance(instanceId);
  const name = markerName(instanceId);
  const current = await ssm.send(new GetParameterCommand({ Name: name }));
  const marker = parseMarker(current.Parameter && current.Parameter.Value);
  if (marker.state === state) {
    return { ok: true, runner_name: runnerName(instanceId) };
  }
  if (state === "ready" && marker.state !== "claimed") {
    throw new Error("runner bootstrap cannot transition to ready");
  }
  if (state === "failed" && !["claimed", "ready"].includes(marker.state)) {
    throw new Error("runner bootstrap cannot transition to failed");
  }
  await ssm.send(new PutParameterCommand({
    Name: name, Type: "String", Value: markerValue(state), Overwrite: true,
  }));
  return { ok: true, runner_name: runnerName(instanceId) };
}

async function bootstrap(event) {
  const instanceId = validateInstanceId(event.instance_id);
  const marker = await claimBootstrap(instanceId);
  try {
    const [downloadUrl, token] = await Promise.all([
      runnerDownloadUrl(), registrationToken(),
    ]);
    return { download_url: downloadUrl, registration_token: token };
  } catch (error) {
    await ssm.send(new PutParameterCommand({
      Name: marker, Type: "String", Value: markerValue("failed"), Overwrite: true,
    })).catch(() => {});
    throw error;
  }
}

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
        markers.set(instanceId, parseMarker(parameter.Value));
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
    if (!completionMatches && now - marker.at < readyGrace) {
      await writeLifecycleState({ ...state, idle_since: 0 });
      return { action: "kept", reason: "runner_startup_window" };
    }
    const progressMatches = progress.action === "in_progress" &&
      progress.runner_name === expectedName;
    if (!completionMatches && progressMatches &&
        now - progress.at < jobEventTimeout) {
      await writeLifecycleState({
        ...state, idle_since: 0, online_instance_id: instanceId,
      });
      return { action: "kept", reason: "job_event_in_progress" };
    }
    if (!completionMatches && !wasOnline) {
      return retryBootstrap(
        instanceId, current, state, activity, "runner_never_online",
      );
    }
    return terminateHost({
      instanceId,
      loadRunners: async () => current,
      state: {
        ...state, idle_since: 0, bootstrap_failures: 0,
        online_instance_id: "",
      },
      activity,
      reason: "ephemeral_runner_finished",
      decrementDesired: false,
    });
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
    if (action === "bootstrap") return bootstrap(event);
    if (action === "ready") {
      return updateBootstrapState(validateInstanceId(event.instance_id), "ready");
    }
    if (action === "failed") {
      return updateBootstrapState(validateInstanceId(event.instance_id), "failed");
    }
  } else if (brokerMode === "reaper" && action === "reap") {
    return reapFleet();
  }
  throw new Error("unsupported runner broker action");
}
