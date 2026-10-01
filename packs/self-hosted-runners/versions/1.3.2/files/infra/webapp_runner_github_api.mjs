/** Repository-scoped GitHub App operations used by trusted runner Lambdas. */

import { createSign } from "node:crypto";
import {
  GetSecretValueCommand,
  SecretsManagerClient,
} from "@aws-sdk/client-secrets-manager";

const secrets = new SecretsManagerClient({});
const apiBase = validatedApiBase(required("GITHUB_API_URL"));
const appIssuer = required("GITHUB_APP_ISSUER");
const installationId = positiveIntegerString(
  required("GITHUB_INSTALLATION_ID"), "GITHUB_INSTALLATION_ID",
);
const repositoryId = positiveIntegerString(
  required("GITHUB_REPOSITORY_ID"), "GITHUB_REPOSITORY_ID",
);
const repoOwner = repositorySegment("GITHUB_REPO_OWNER");
const repoName = repositorySegment("GITHUB_REPO_NAME");
const privateKeySecretArn = required("GITHUB_PRIVATE_KEY_SECRET_ARN");
export const runnerArchitecture = required("RUNNER_ARCHITECTURE");
export const runnerPrefix = required("RUNNER_PREFIX");
export const runnerLabels = new Set(
  required("RUNNER_LABELS").split(",").map((value) => value.toLowerCase()),
);

function required(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function validatedApiBase(value) {
  if (/[\s\u0000-\u001f\u007f\\]/.test(value)) {
    throw new Error("GITHUB_API_URL contains unsafe characters");
  }
  const parsed = new URL(value);
  const path = parsed.pathname.replace(/\/$/, "");
  const host = parsed.hostname.toLowerCase();
  const publicCloud = host === "api.github.com" && !parsed.port && !path;
  const dataResidency = host.startsWith("api.") &&
    host.endsWith(".ghe.com") && !path;
  const enterpriseServer = !["github.com", "api.github.com"].includes(host) &&
    path === "/api/v3";
  if (parsed.protocol !== "https:" || parsed.username || parsed.password ||
      parsed.search || parsed.hash ||
      !(publicCloud || dataResidency || enterpriseServer)) {
    throw new Error("GITHUB_API_URL must be a canonical GitHub HTTPS API base");
  }
  return `${parsed.origin}${path}`;
}

function positiveIntegerString(value, name) {
  if (!/^[1-9]\d*$/.test(value)) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function repositorySegment(name) {
  const value = required(name);
  if (!/^[A-Za-z0-9_.-]+$/.test(value) || value === "." || value === "..") {
    throw new Error(`${name} is not a valid GitHub repository segment`);
  }
  return value;
}

function base64url(value) {
  return Buffer.from(value).toString("base64url");
}

async function privateKey() {
  const result = await secrets.send(new GetSecretValueCommand({
    SecretId: privateKeySecretArn,
  }));
  const value = String(result.SecretString || "").trim();
  if (!value) throw new Error("GitHub App private-key secret is empty");
  return value;
}

async function appJwt() {
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64url(JSON.stringify({
    iat: now - 60, exp: now + 540, iss: appIssuer,
  }));
  const unsigned = `${header}.${payload}`;
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  signer.end();
  const signature = signer.sign(await privateKey()).toString("base64url");
  return `${unsigned}.${signature}`;
}

async function responseJson(response, operation) {
  const text = await response.text();
  let body = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch (_error) {
      throw new Error(`GitHub ${operation} returned a non-JSON response`);
    }
  }
  if (!response.ok) {
    throw new Error(
      `GitHub ${operation} failed: ${String(body.message || `HTTP ${response.status}`)}`,
    );
  }
  return body;
}

async function installationToken(permissions) {
  const response = await fetch(
    `${apiBase}/app/installations/${installationId}/access_tokens`,
    {
      method: "POST",
      redirect: "error",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${await appJwt()}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        repository_ids: [Number(repositoryId)],
        permissions,
      }),
    },
  );
  const body = await responseJson(response, "installation-token request");
  if (!body.token || !body.expires_at) {
    throw new Error("GitHub installation-token response omitted token expiry");
  }
  return { token: body.token, expires_at: body.expires_at };
}

function repositoryApi(path) {
  const owner = encodeURIComponent(repoOwner);
  const name = encodeURIComponent(repoName);
  return `${apiBase}/repos/${owner}/${name}${path}`;
}

async function githubRequest(path, { method = "GET", allowNotFound = false } = {}) {
  const response = await fetch(repositoryApi(path), {
    method,
    redirect: "error",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${(
        await installationToken({ administration: "write" })
      ).token}`,
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (allowNotFound && response.status === 404) return {};
  return responseJson(response, `${method} ${path}`);
}

export async function providerToken(authority) {
  const expected = {
    repo: `${repoOwner}/${repoName}`,
    repo_owner: repoOwner,
    repo_name: repoName,
    installation_id: installationId,
    repository_id: repositoryId,
    app_issuer: appIssuer,
    api_url: apiBase,
  };
  if (!authority || typeof authority !== "object" || Array.isArray(authority)) {
    throw new Error("runner provider authority is invalid");
  }
  const mismatched = Object.entries(expected)
    .filter(([key, value]) => String(authority[key] || "") !== value)
    .map(([key]) => key);
  if (mismatched.length) {
    throw new Error(
      `runner provider authority mismatch: ${mismatched.sort().join(", ")}`,
    );
  }
  const grant = await installationToken({
    actions_variables: "read",
    repository_hooks: "read",
  });
  return { ...grant, repository: expected.repo };
}

export async function registrationToken() {
  const result = await githubRequest("/actions/runners/registration-token", {
    method: "POST",
  });
  if (!result.token) throw new Error("GitHub registration-token response omitted token");
  return result.token;
}

export async function runnerDownloadUrl() {
  const downloads = await githubRequest("/actions/runners/downloads");
  const selected = (Array.isArray(downloads) ? downloads : []).find(
    (item) => item.os === "linux" && item.architecture === runnerArchitecture,
  );
  if (!selected || !selected.download_url ||
      new URL(selected.download_url).protocol !== "https:") {
    throw new Error("GitHub runner downloads omitted the configured Linux architecture");
  }
  return selected.download_url;
}

export async function listRunners() {
  const runners = [];
  let expectedTotal;
  for (let page = 1; page <= 100; page += 1) {
    const result = await githubRequest(`/actions/runners?per_page=100&page=${page}`);
    if (!Number.isSafeInteger(result.total_count) || result.total_count < 0 ||
        !Array.isArray(result.runners)) {
      throw new Error("GitHub runner listing returned an invalid pagination payload");
    }
    if (expectedTotal === undefined) expectedTotal = result.total_count;
    if (result.total_count !== expectedTotal) {
      throw new Error("GitHub runner total_count changed during pagination");
    }
    const before = runners.length;
    runners.push(...result.runners);
    if (runners.length >= expectedTotal) return runners;
    if (runners.length === before) {
      throw new Error("GitHub runner listing ended before total_count was retrieved");
    }
  }
  throw new Error("GitHub runner listing exceeded the supported pagination limit");
}

export async function deleteRunner(id) {
  const value = positiveIntegerString(String(id || ""), "runner_id");
  await githubRequest(`/actions/runners/${encodeURIComponent(value)}`, {
    method: "DELETE", allowNotFound: true,
  });
}
