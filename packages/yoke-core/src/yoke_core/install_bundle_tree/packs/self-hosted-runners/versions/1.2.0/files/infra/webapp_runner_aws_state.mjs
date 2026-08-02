/** AWS lifecycle state operations shared by the runner broker modes. */

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
    if (!Number.isSafeInteger(state.idle_since) || state.idle_since < 0 ||
        typeof state.queue_activity !== "string" || !state.queue_activity ||
        !Number.isSafeInteger(state.bootstrap_failures) ||
        state.bootstrap_failures < 0 ||
        typeof state.online_instance_id !== "string") {
      throw new Error("invalid lifecycle fields");
    }
    return state;
  } catch (_error) {
    throw new Error("runner lifecycle state is malformed");
  }
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
  const launch = match && new Date(match.LaunchTime).getTime() / 1000;
  if (!Number.isFinite(launch) || launch <= 0) {
    throw new Error("runner instance launch time is unavailable");
  }
  return launch;
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
        !Number.isSafeInteger(event.at) || event.at < 0) {
      throw new Error("invalid runner event fields");
    }
    return event;
  } catch (_error) {
    throw new Error("runner lifecycle event is malformed");
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
    idle_since: 0, queue_activity: activity, bootstrap_failures: 0,
    online_instance_id: state.online_instance_id,
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
