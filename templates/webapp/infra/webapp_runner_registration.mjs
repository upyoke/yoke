/** Instance-bound GitHub runner registration and bootstrap state. */

import {
  GetParameterCommand,
  PutParameterCommand,
  SSMClient,
} from "@aws-sdk/client-ssm";
import {
  registrationToken,
  runnerDownloadUrl,
  runnerPrefix,
} from "./webapp_runner_github_api.mjs";
import { assertActiveInstance } from "./webapp_runner_aws_state.mjs";

const ssm = new SSMClient({});
export const bootstrapMarkerPrefix = required(
  "BOOTSTRAP_MARKER_PREFIX",
).replace(/\/$/, "");

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function nowSeconds() { return Math.floor(Date.now() / 1000); }

function validateInstanceId(value) {
  const instanceId = String(value || "");
  if (!/^i-[0-9a-f]{8,17}$/.test(instanceId)) {
    throw new Error("instance_id must be an EC2 instance id");
  }
  return instanceId;
}

function markerName(instanceId) {
  return `${bootstrapMarkerPrefix}/${instanceId}`;
}

function runnerName(instanceId) { return `${runnerPrefix}${instanceId}`; }

function markerValue(state, at = nowSeconds()) {
  return JSON.stringify({ state, at });
}

export function parseBootstrapMarker(value) {
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

export async function updateBootstrapState(rawInstanceId, state) {
  const instanceId = validateInstanceId(rawInstanceId);
  await assertActiveInstance(instanceId);
  const name = markerName(instanceId);
  const current = await ssm.send(new GetParameterCommand({ Name: name }));
  const marker = parseBootstrapMarker(
    current.Parameter && current.Parameter.Value,
  );
  if (marker.state === state) {
    await ssm.send(new PutParameterCommand({
      Name: name, Type: "String", Value: markerValue(state), Overwrite: true,
    }));
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

export async function registerRunner(rawInstanceId) {
  const instanceId = validateInstanceId(rawInstanceId);
  await assertActiveInstance(instanceId);
  const current = await ssm.send(new GetParameterCommand({
    Name: markerName(instanceId),
  }));
  const marker = parseBootstrapMarker(
    current.Parameter && current.Parameter.Value,
  );
  if (marker.state !== "ready") {
    throw new Error("runner host is not ready for another registration");
  }
  return { registration_token: await registrationToken() };
}

export async function bootstrapRunnerHost(rawInstanceId) {
  const instanceId = validateInstanceId(rawInstanceId);
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
