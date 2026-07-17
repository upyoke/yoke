// AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_termination.mjs. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
/** Durable, idempotent host termination and post-termination cleanup. */

import {
  DeleteParameterCommand,
  PutParameterCommand,
  SSMClient,
} from "@aws-sdk/client-ssm";
import { deleteRunner } from "./webapp_runner_github_api.mjs";
import {
  readQueueActivity,
  restoreDesiredCapacity,
  terminateInstance,
  writeLifecycleState,
} from "./webapp_runner_aws_state.mjs";

const ssm = new SSMClient({});
const markerPrefix = required("BOOTSTRAP_MARKER_PREFIX").replace(/\/$/, "");
const terminationStates = new Set([
  "termination_requested", "termination_acknowledged",
]);

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function markerName(instanceId) {
  return `${markerPrefix}/${instanceId}`;
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function validLifecycleState(state) {
  return state && typeof state === "object" &&
    Number.isSafeInteger(state.idle_since) && state.idle_since >= 0 &&
    typeof state.queue_activity === "string" && state.queue_activity &&
    Number.isSafeInteger(state.bootstrap_failures) &&
    state.bootstrap_failures >= 0 &&
    typeof state.online_instance_id === "string";
}

export function parseTerminationRecord(value) {
  let record;
  try {
    record = JSON.parse(String(value || ""));
  } catch (_error) {
    return null;
  }
  if (!record || typeof record !== "object" ||
      !terminationStates.has(record.state)) return null;
  if (!/^i-[0-9a-f]{8,17}$/.test(record.instance_id) ||
      !Number.isSafeInteger(record.at) || record.at <= 0 ||
      typeof record.reason !== "string" || !record.reason ||
      typeof record.decrement_desired !== "boolean" ||
      typeof record.observed_activity !== "string" ||
      !record.observed_activity ||
      !Number.isSafeInteger(record.termination_attempts) ||
      record.termination_attempts <= 0 ||
      !["none", "required", "completed"].includes(record.capacity_restore) ||
      !validLifecycleState(record.lifecycle_state)) {
    throw new Error("runner termination marker is malformed");
  }
  return record;
}

async function writeRecord(record) {
  await ssm.send(new PutParameterCommand({
    Name: markerName(record.instance_id),
    Type: "String",
    Value: JSON.stringify(record),
    Overwrite: true,
  }));
  return record;
}

function acknowledged(record) {
  return {
    ...record,
    state: "termination_acknowledged",
    at: nowSeconds(),
  };
}

async function reconcileCapacity(record) {
  if (!record.decrement_desired || record.capacity_restore === "completed") {
    return record;
  }
  let next = record;
  if (next.capacity_restore === "none") {
    const latestActivity = await readQueueActivity();
    if (latestActivity === next.observed_activity) return next;
    next = await writeRecord({
      ...next,
      reason: "queue_activity_race",
      capacity_restore: "required",
      lifecycle_state: {
        idle_since: 0,
        queue_activity: latestActivity,
        bootstrap_failures: 0,
        online_instance_id: "",
      },
    });
  }
  await restoreDesiredCapacity();
  return writeRecord({ ...next, capacity_restore: "completed" });
}

async function completeTermination(record, loadRunners) {
  const reconciled = await reconcileCapacity(record);
  for (const runner of await loadRunners()) await deleteRunner(runner.id);
  await writeLifecycleState(reconciled.lifecycle_state);
  await ssm.send(new DeleteParameterCommand({
    Name: markerName(reconciled.instance_id),
  }));
  return {
    action: reconciled.decrement_desired &&
      reconciled.reason !== "queue_activity_race" ? "scaled_down" : "replaced",
    reason: reconciled.reason,
  };
}

export async function terminateHost({
  instanceId,
  loadRunners,
  state,
  activity,
  reason,
  decrementDesired,
}) {
  const requested = await writeRecord({
    state: "termination_requested",
    instance_id: instanceId,
    at: nowSeconds(),
    reason,
    decrement_desired: decrementDesired,
    observed_activity: activity,
    termination_attempts: 1,
    capacity_restore: "none",
    lifecycle_state: { ...state, idle_since: 0, online_instance_id: "" },
  });
  await terminateInstance(instanceId, decrementDesired);
  const record = await writeRecord(acknowledged(requested));
  return completeTermination(record, loadRunners);
}

export async function resumeTermination({
  record,
  instanceActive,
  loadRunners,
  maxAttempts,
}) {
  let next = record;
  if (next.state === "termination_requested") {
    if (instanceActive) {
      if (next.termination_attempts >= maxAttempts) {
        throw new Error("runner termination retry budget exhausted");
      }
      next = await writeRecord({
        ...next,
        at: nowSeconds(),
        termination_attempts: next.termination_attempts + 1,
      });
      await terminateInstance(next.instance_id, next.decrement_desired);
    }
    next = await writeRecord(acknowledged(next));
  } else if (instanceActive) {
    return { action: "kept", reason: "termination_pending" };
  }
  return completeTermination(next, loadRunners);
}
