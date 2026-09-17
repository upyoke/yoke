// Authoring a deployment flow from the catalog: the actions an operator has,
// what each one calls, and the check the screen makes them pass first.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

const FLOWS = [
  {
    id: "alpha-release", name: "Alpha Release", project: "alpha",
    project_id: 1, status: "active", target_tier: "persistent",
    target_environment: "prod", on_failure: "halt",
    description: "Ship alpha", stages: [{ name: "build" }, { name: "verify" }],
  },
  {
    id: "alpha-legacy", name: "Alpha Legacy", project: "alpha",
    project_id: 1, status: "disabled", target_tier: "persistent",
    target_environment: "stage", on_failure: "continue",
    stages: [{ name: "archive" }],
  },
];

const VALID = {
  project: "1",
  valid: true,
  execution_supported: true,
  definition_schema_version: 4,
  serving_schema_version: 4,
  unsupported_target_kinds: [],
  unprovable_qa_identity_stages: [],
};

function flowClient({ flows = FLOWS, overrides = {} } = {}) {
  const calls = [];
  return {
    calls,
    async call(request) {
      calls.push(request);
      const override = overrides[request.function];
      if (override) return override(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [
          { id: 1, slug: "alpha", name: "Alpha" },
          { id: 2, slug: "beta", name: "Beta" },
        ] });
      }
      if (request.function === "workflows.definition.get") {
        const project = request.payload.project;
        return ok({
          flows: project === "1" ? flows : project === "2" ? [] : flows,
        });
      }
      if (request.function === "deployment_flows.validate") return ok(VALID);
      if (request.function.startsWith("deployment_flows.")) {
        return ok({ flow_id: request.payload.flow_id || "new-flow", flow: {} });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountFlows(t, client, hash = "#/deployments/flows?project=1") {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.body = documentNode.createElement("body");
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  t.after(() => mounted.unmount());
  return { documentNode, root };
}

function action(root, label) {
  return byClass(root, "delivery-flow-action")
    .find((node) => node.textContent === label);
}

function fieldControl(root, label) {
  const field = byClass(root, "delivery-flow-field")
    .find((node) => node.children[0]?.textContent === label);
  return field?.children[1];
}

test("the catalog offers the four things an operator does to a definition", async (t) => {
  const { root } = await mountFlows(t, flowClient());

  assert.deepEqual(
    byClass(root, "delivery-flow-action").map((node) => node.textContent),
    ["New flow", "Edit", "New version", "Disable"],
  );
  // A flow is selected, so every action that needs one is reachable.
  for (const label of ["Edit", "New version", "Disable"]) {
    assert.equal(action(root, label).disabled, false, label);
  }
  // Retiring a definition destroys nothing, and the control says so rather
  // than reading like a delete.
  assert.match(
    action(root, "Disable").getAttribute("title"),
    /Runs that already froze it are unaffected/,
  );
});

test("a disabled definition offers the way back rather than a second disable", async (t) => {
  const { root } = await mountFlows(
    t, flowClient(), "#/deployments/flows/alpha-legacy?project=1",
  );

  const status = byClass(root, "delivery-flow-action")[3];
  assert.equal(status.textContent, "Enable");
  assert.match(status.getAttribute("title"), /available to new runs again/);
});

test("nothing is written until the serving runtime has answered for it", async (t) => {
  const client = flowClient();
  const { root } = await mountFlows(t, client);
  action(root, "New flow").dispatchEvent(new Event("click"));
  await settle();

  const save = byClass(root, "workflow-button")
    .find((node) => node.textContent === "Create flow");
  assert.equal(save.disabled, true);

  fieldControl(root, "Flow id").value = "alpha-preview";
  fieldControl(root, "Name").value = "Alpha Preview";
  fieldControl(root, "Stages").value = '[{"name":"build"}]';
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Validate definition")
    .dispatchEvent(new Event("click"));
  await settle();

  const validation = byClass(root, "delivery-flow-validation")[0];
  assert.match(validation.textContent, /Definition is valid/);
  assert.match(validation.textContent, /Every stage target is executable/);
  assert.equal(validation.classList.contains("is-valid"), true);
  assert.equal(save.disabled, false);

  save.dispatchEvent(new Event("click"));
  await settle();
  const created = client.calls.find(
    (call) => call.function === "deployment_flows.create",
  );
  assert.equal(created.payload.flow_id, "alpha-preview");
  assert.equal(created.payload.stages, '[{"name":"build"}]');
  // Creation is the one call whose project is not implied by an existing
  // definition, so it rides on the target.
  assert.deepEqual(created.target, { kind: "global", project_id: "1" });
});

test("a runtime that cannot execute a stage target refuses the save", async (t) => {
  const client = flowClient({
    overrides: {
      "deployment_flows.validate": () => ok({
        ...VALID,
        valid: true,
        execution_supported: false,
        unsupported_target_kinds: ["run_preview"],
        unprovable_qa_identity_stages: ["sign-off"],
      }),
    },
  });
  const { root } = await mountFlows(t, client);
  action(root, "New flow").dispatchEvent(new Event("click"));
  await settle();
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Validate definition")
    .dispatchEvent(new Event("click"));
  await settle();

  const validation = byClass(root, "delivery-flow-validation")[0];
  assert.equal(validation.classList.contains("is-invalid"), true);
  assert.match(validation.textContent, /cannot execute every stage target/);
  assert.match(validation.textContent, /Unsupported target kinds: run_preview/);
  assert.match(validation.textContent, /cannot prove who ruled on them: sign-off/);
  assert.equal(
    byClass(root, "workflow-button")
      .find((node) => node.textContent === "Create flow").disabled,
    true,
  );
});

test("editing the stages retracts a verdict that no longer answers for them", async (t) => {
  const { root } = await mountFlows(t, flowClient());
  action(root, "Edit").dispatchEvent(new Event("click"));
  await settle();

  const save = byClass(root, "workflow-button")
    .find((node) => node.textContent === "Save changes");
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Validate definition")
    .dispatchEvent(new Event("click"));
  await settle();
  assert.equal(save.disabled, false);

  const stages = fieldControl(root, "Stages");
  stages.value = '[{"name":"build"},{"name":"deploy"}]';
  stages.dispatchEvent(new Event("input"));
  assert.equal(save.disabled, true);
  assert.equal(byClass(root, "delivery-flow-validation")[0].hidden, true);
});

test("editing opens on the definition and keeps its identity fixed", async (t) => {
  const client = flowClient();
  const { root } = await mountFlows(t, client);
  action(root, "Edit").dispatchEvent(new Event("click"));
  await settle();

  assert.equal(fieldControl(root, "Flow id").value, "alpha-release");
  assert.equal(fieldControl(root, "Flow id").disabled, true);
  assert.equal(fieldControl(root, "Name").value, "Alpha Release");
  assert.equal(fieldControl(root, "Project").disabled, true);
  // The stages an operator edits are the ones the definition actually holds.
  assert.deepEqual(
    JSON.parse(fieldControl(root, "Stages").value),
    [{ name: "build" }, { name: "verify" }],
  );

  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Validate definition")
    .dispatchEvent(new Event("click"));
  await settle();
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Save changes")
    .dispatchEvent(new Event("click"));
  await settle();
  const updated = client.calls.find(
    (call) => call.function === "deployment_flows.update",
  );
  assert.equal(updated.payload.flow_id, "alpha-release");
  assert.equal(updated.payload.changes.name, "Alpha Release");
});

test("a new version supersedes its source rather than editing it", async (t) => {
  const client = flowClient();
  const { root } = await mountFlows(t, client);
  action(root, "New version").dispatchEvent(new Event("click"));
  await settle();

  // The identity is the one thing a version must not inherit.
  assert.equal(fieldControl(root, "Flow id").value, "");
  assert.equal(fieldControl(root, "Flow id").disabled, false);
  assert.equal(fieldControl(root, "Project").disabled, true);
  // A version lands disabled: it assigns to nothing until somebody says so.
  assert.equal(fieldControl(root, "Status").value, "disabled");

  fieldControl(root, "Flow id").value = "alpha-release-v2";
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Validate definition")
    .dispatchEvent(new Event("click"));
  await settle();
  byClass(root, "workflow-button")
    .find((node) => node.textContent === "Create version")
    .dispatchEvent(new Event("click"));
  await settle();

  const versioned = client.calls.find(
    (call) => call.function === "deployment_flows.version",
  );
  assert.equal(versioned.payload.source_flow_id, "alpha-release");
  assert.equal(versioned.payload.new_flow_id, "alpha-release-v2");
  assert.equal(versioned.payload.status, "disabled");
});

test("taking a definition out of service names what it is doing", async (t) => {
  const client = flowClient();
  const { root } = await mountFlows(t, client);
  action(root, "Disable").dispatchEvent(new Event("click"));
  await settle();

  const call = client.calls.find(
    (entry) => entry.function === "deployment_flows.set_status",
  );
  assert.deepEqual(call.payload, {
    flow_id: "alpha-release", status: "disabled",
  });
});

test("a refused write is reported rather than read as success", async (t) => {
  const client = flowClient({
    overrides: {
      "deployment_flows.set_status": () => ({
        status: 403,
        envelope: { success: false, error: { message: "not permitted here" } },
      }),
    },
  });
  const { root } = await mountFlows(t, client);
  action(root, "Disable").dispatchEvent(new Event("click"));
  await settle();

  const report = byClass(root, "delivery-flow-report")[0];
  assert.equal(report.hidden, false);
  assert.match(report.textContent, /not permitted here/);
  assert.equal(report.classList.contains("is-invalid"), true);
  assert.equal(action(root, "Disable").disabled, false);
});

test("a universe with no flows can still author its first one", async (t) => {
  const { root } = await mountFlows(
    t, flowClient({ flows: [] }), "#/deployments/flows?project=2",
  );

  assert.equal(byClass(root, "delivery-flow-card").length, 0);
  const first = byClass(root, "delivery-flow-action")[0];
  assert.equal(first.textContent, "New flow");
  first.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "delivery-flow-form").length, 1);
});
