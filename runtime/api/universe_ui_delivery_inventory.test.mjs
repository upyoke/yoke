import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

function deliveryClient() {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260726-010",
            project: "yoke",
            project_id: 1,
            target_tier: "persistent",
            target_environment: "prod",
            status: "succeeded",
            completed_at: "2026-07-26T14:00:00Z",
          }],
        });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({
          project: request.payload.project,
          sites: [{ name: "Application" }],
          environments: [{
            site: "Application",
            name: "prod",
            url: "https://app.example",
            deploy_method: "github-actions",
            health_check_url: "https://app.example/health",
            last_deployed_at: "2026-07-26T12:00:00Z",
          }],
        });
      }
      if (request.function === "projects.environment_settings.get") {
        return okEnvelope({
          project: request.payload.project,
          environment: request.payload.environment,
          values: { "git.branch": "main" },
        });
      }
      if (request.function === "projects.capabilities.list") {
        return okEnvelope({
          rows: [{
            type: "migration_model",
            display_type: "migration_model",
            kind: "declared_model",
            state: "ready",
            project_id: 1,
            project: "yoke",
            settings_summary: "primary (governed_module)",
          }, {
            type: "aws-admin",
            kind: "provider_access",
            state: "ready",
            project_id: 1,
            project: "yoke",
            settings_summary: "region=us-east-1",
          }],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

test("Environments joins branch and latest-run reads without inventing policy", async (t) => {
  const client = deliveryClient();
  const { root, mounted } = await mountAt(
    t, "#/environments?project=1", client,
  );

  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.equal(byClass(root, "scope-bar").length, 1);
  assert.deepEqual(
    client.requests.filter((request) => [
      "projects.infrastructure.list",
      "projects.environment_settings.get",
      "deployment_runs.list",
    ].includes(request.function)),
    [
      {
        function: "projects.infrastructure.list",
        payload: { project: "1" },
      },
      {
        function: "projects.environment_settings.get",
        payload: {
          project: "1",
          environment: "prod",
          paths: ["git.branch"],
        },
      },
      { function: "deployment_runs.list", payload: { project: "1" } },
    ],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["environment", "branch", "auto-deploy", "status", "last deploy"],
  );
  const cells = allNodes(root).filter((node) => node.tagName === "TD");
  assert.deepEqual(cells.slice(0, 4).map(cellText), [
    "prod", "main", "not exposed", "succeeded",
  ]);
  assert.notEqual(cellText(cells[4]), "never");
  assert.ok(byClass(root, "delivery-read-note")[0].children[1].textContent
    .includes("Auto-deploy policy has no published browser read"));

  const raw = byClass(root, "raw-json")[0];
  assert.equal(raw.hidden, true);
  byClass(root, "raw-toggle")[0].dispatchEvent(new Event("click"));
  assert.equal(raw.hidden, false);
  assert.ok(raw.textContent.includes("health_check_url"));
  mounted.unmount();
});

test("Environment inventory fans out at All and labels each project", async (t) => {
  const requests = [];
  const client = {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [
          { id: 1, slug: "alpha", name: "Alpha" },
          { id: 2, slug: "beta", name: "Beta" },
        ] });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({
          project: request.payload.project,
          sites: [],
          environments: [{
            name: "prod",
          }],
        });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({ rows: [] });
      }
      if (request.function === "projects.environment_settings.get") {
        return okEnvelope({
          project: request.payload.project,
          environment: request.payload.environment,
          values: {
            "git.branch": request.payload.project === "1"
              ? "alpha-main" : "beta-main",
          },
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t, "#/environments", client,
  );

  assert.deepEqual(
    requests.filter(
      (request) => request.function === "projects.infrastructure.list",
    ),
    [
      {
        function: "projects.infrastructure.list",
        payload: { project: "1" },
      },
      {
        function: "projects.infrastructure.list",
        payload: { project: "2" },
      },
    ],
  );
  assert.deepEqual(
    requests.find(
      (request) => request.function === "deployment_runs.list",
    ),
    { function: "deployment_runs.list", payload: {} },
  );
  assert.deepEqual(
    requests.filter(
      (request) =>
        request.function === "projects.environment_settings.get",
    ),
    [
      {
        function: "projects.environment_settings.get",
        payload: {
          project: "1",
          environment: "prod",
          paths: ["git.branch"],
        },
      },
      {
        function: "projects.environment_settings.get",
        payload: {
          project: "2",
          environment: "prod",
          paths: ["git.branch"],
        },
      },
    ],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "environment", "project", "branch", "auto-deploy",
      "status", "last deploy",
    ],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD")
      .map(cellText).filter((text) => [
        "alpha", "beta", "alpha-main", "beta-main",
      ].includes(text)),
    ["alpha", "alpha-main", "beta", "beta-main"],
  );
  mounted.unmount();
});

test("Databases renders declared models and labels every unserved steering fact", async (t) => {
  const client = deliveryClient();
  const { root, mounted } = await mountAt(
    t, "#/databases?project=1", client,
  );

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "projects.capabilities.list",
    ),
    { function: "projects.capabilities.list", payload: { project: "1" } },
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["model", "authority", "posture", "last apply", "state"],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD").map(cellText),
    [
      "primary (governed_module)", "project capability",
      "not exposed", "not exposed", "ready",
    ],
  );
  assert.equal(byClass(root, "pill")[0].attributes.get("data-state"), "ready");
  assert.ok(byClass(root, "delivery-read-note")[0].children[1].textContent
    .includes("claims, and leases have no browser read"));
  mounted.unmount();
});

test("Infrastructure is structurally complete but does not claim provider parity", async (t) => {
  const client = deliveryClient();
  const { root, mounted } = await mountAt(
    t, "#/infrastructure?project=1", client,
  );

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "projects.infrastructure.list",
    ),
    {
      function: "projects.infrastructure.list",
      payload: { project: "1" },
    },
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["environment", "project", "what backs it", "code source", "state"],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD").map(cellText),
    ["prod", "yoke", "not exposed", "project-owned", "declared"],
  );
  assert.ok(byClass(root, "delivery-read-note")[0].children[1].textContent
    .includes("does not compare live provider state"));
  assert.equal(byClass(root, "table-wrap").length, 1);
  mounted.unmount();
});
