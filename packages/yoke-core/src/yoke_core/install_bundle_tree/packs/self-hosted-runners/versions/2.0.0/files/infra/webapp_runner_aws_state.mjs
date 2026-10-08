/** AWS lifecycle state operations shared by the runner broker modes. */

import { canonicalInstant } from "./webapp_runner_clock.mjs";
import { instantFromDate } from "./webapp_runner_timestamps.mjs";

import {
  AutoScalingClient,
  DescribeAutoScalingInstancesCommand,
  SetDesiredCapacityCommand,
  TerminateInstanceInAutoScalingGroupCommand,
} from "@aws-sdk/client-auto-scaling";
import { DescribeInstancesCommand, EC2Client } from "@aws-sdk/client-ec2";
import {
  GetParameterCommand,
  PutParameterCommand,
  SSMClient,
} from "@aws-sdk/client-ssm";

const autoscaling = new AutoScalingClient({});
const ec2 = new EC2Client({});
const ssm = new SSMClient({});
const asgName = required("RUNNER_ASG_NAME");
const lifecycleStateParameter = required("LIFECYCLE_STATE_PARAMETER");
const queueActivityParameter = required("QUEUE_ACTIVITY_PARAMETER");
const runnerProgressParameter = required("RUNNER_PROGRESS_PARAMETER");
const runnerCompletionParameter = required("RUNNER_COMPLETION_PARAMETER");
const desiredRunnerCount = positiveInteger(
  required("DESIRED_RUNNER_COUNT"), "DESIRED_RUNNER_COUNT",
);

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function positiveInteger(value, name) {
  if (!/^[1-9]\d*$/.test(value)) throw new Error(`${name} must be positive`);
  return Number(value);
}

function parseLifecycleState(value) {
  try {
    const state = JSON.parse(String(value || ""));
    if (!validLifecycleState(state)) {
      throw new Error("invalid lifecycle fields");
    }
    return state;
  } catch (_error) {
    throw new Error("runner_lifecycle_instant_invalid: pause writers and convert snapshotted lifecycle state to canonical UTC before resuming");
  }
}

export function validLifecycleState(state) {
  try {
    if (!state || typeof state !== "object" ||
        typeof state.queue_activity !== "string" || !state.queue_activity ||
        !Number.isSafeInteger(state.bootstrap_failures) || state.bootstrap_failures < 0 ||
        typeof state.online_instance_id !== "string" ||
        !state.idle_by_instance || typeof state.idle_by_instance !== "object" ||
        Array.isArray(state.idle_by_instance)) return false;
    if (state.idle_since !== null) canonicalInstant(state.idle_since);
    for (const [instanceId, instant] of Object.entries(state.idle_by_instance)) {
      if (!/^i-[0-9a-f]{8,17}$/.test(instanceId)) return false;
      canonicalInstant(instant);
    }
    return true;
  } catch (_) { return false; }
}

export async function currentAsgInstanceIds() {
  const ids = new Set();
  let nextToken;
  do {
    const page = await autoscaling.send(new DescribeAutoScalingInstancesCommand({
      MaxRecords: 50, NextToken: nextToken,
    }));
    for (const item of page.AutoScalingInstances || []) {
      if (item.AutoScalingGroupName === asgName && item.InstanceId &&
          !String(item.LifecycleState || "").includes("Terminating")) {
        ids.add(item.InstanceId);
      }
    }
    nextToken = page.NextToken;
  } while (nextToken);
  return ids;
}

export async function assertActiveInstance(instanceId) {
  if (!(await currentAsgInstanceIds()).has(instanceId)) {
    throw new Error("instance_id is not active in the configured runner ASG");
  }
}

export async function instanceLaunchTime(instanceId) {
  const result = await ec2.send(new DescribeInstancesCommand({
    InstanceIds: [instanceId],
  }));
  const instances = (result.Reservations || []).flatMap(
    (reservation) => reservation.Instances || [],
  );
  const match = instances.find((instance) => instance.InstanceId === instanceId);
  const launch = match && new Date(match.LaunchTime);
  if (!launch || !Number.isFinite(launch.getTime())) {
    throw new Error("runner instance launch time is unavailable");
  }
  return instantFromDate(launch);
}

export async function readQueueActivity() {
  const result = await ssm.send(new GetParameterCommand({
    Name: queueActivityParameter,
  }));
  const value = String(result.Parameter && result.Parameter.Value || "");
  if (!value) throw new Error("runner queue activity is unavailable");
  return value;
}

async function readRunnerEvent(parameterName, expectedAction) {
  const result = await ssm.send(new GetParameterCommand({
    Name: parameterName,
  }));
  try {
    const event = JSON.parse(String(result.Parameter && result.Parameter.Value || ""));
    if (!["none", expectedAction].includes(event.action) ||
        typeof event.runner_name !== "string" ||
        typeof event.job_id !== "string" ||
        (event.action === "none" ? event.at !== null : canonicalInstant(event.at) !== event.at)) {
      throw new Error("invalid runner event fields");
    }
    return event;
  } catch (_error) {
    throw new Error("runner_event_instant_invalid: pause writers and convert snapshotted progress/completion state to canonical UTC before resuming");
  }
}

export async function readRunnerEvents() {
  const [progress, completed] = await Promise.all([
    readRunnerEvent(runnerProgressParameter, "in_progress"),
    readRunnerEvent(runnerCompletionParameter, "completed"),
  ]);
  return { progress, completed };
}

async function readLifecycleState() {
  const result = await ssm.send(new GetParameterCommand({
    Name: lifecycleStateParameter,
  }));
  return parseLifecycleState(result.Parameter && result.Parameter.Value);
}

export async function writeLifecycleState(state) {
  if (!validLifecycleState(state)) {
    throw new Error("runner_lifecycle_instant_invalid: refuse writing malformed lifecycle state; supply canonical UTC instants or null");
  }
  await ssm.send(new PutParameterCommand({
    Name: lifecycleStateParameter,
    Type: "String",
    Value: JSON.stringify(state),
    Overwrite: true,
  }));
}

export async function currentLifecycleState() {
  const [state, activity] = await Promise.all([
    readLifecycleState(), readQueueActivity(),
  ]);
  if (state.queue_activity === activity) {
    return { state, activity, activityChanged: false };
  }
  const reset = {
    idle_since: null, queue_activity: activity, bootstrap_failures: 0,
    online_instance_id: state.online_instance_id,
    // Per-host idle clocks survive this reset. Queue activity changes on every
    // job event, so rebuilding without them would restart every host's clock
    // many times an hour and no host would ever reach the idle window. The
    // parallel reaper re-derives which hosts are idle and floors each carried
    // mark at that host's current registration timestamp, so a completed and
    // rearmed job starts a fresh per-host window.
    idle_by_instance: state.idle_by_instance || {},
  };
  return { state: reset, activity, activityChanged: true };
}

export async function terminateInstance(instanceId, decrementDesired) {
  await autoscaling.send(new TerminateInstanceInAutoScalingGroupCommand({
    InstanceId: instanceId,
    ShouldDecrementDesiredCapacity: decrementDesired,
  }));
}

export async function restoreDesiredCapacity() {
  await autoscaling.send(new SetDesiredCapacityCommand({
    AutoScalingGroupName: asgName,
    DesiredCapacity: desiredRunnerCount,
    HonorCooldown: false,
  }));
}
