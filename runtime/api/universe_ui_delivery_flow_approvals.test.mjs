import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

const STAGES = [
  {
    name: "approve-prod",
    step_runner: "human-approval",
    approvals: { roles: ["operator"], actors: [] },
  },
  { name: "release", step_runner: "auto" },
];

const GATED = {
  id: "alpha-release", name: "Alpha Release", project: "alpha",
  status: "active", target_tier: "persistent", target_environment: "prod",
  on_failure: "halt",
  stage_names: ["approve-prod", "release"],
  approval_stages: [{
    name: "approve-prod",
    approvals: { roles: ["operator"], actors: [] },
  }],
};

const UNGATED = {
  ...GATED,
  id: "alpha-build", name: "Alpha Build",
  stage_names: ["build", "verify"],
  approval_stages: [],
};

function flowClient(flows) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [
          { id: 1, slug: "alpha", name: "Alpha" },
        ] });
      }
      if (request.function === "workflows.definition.get") {
        return okEnvelope({ flows });
      }
      if (request.function === "workflows.mechanics.get") {
        return okEnvelope({ approvers: [{ id: 2, label: "ben" }] });
      }
      if (request.function === "deployment_flows.stages") {
        return okEnvelope({
          flow_id: request.payload.flow_id,
          stages: JSON.stringify(STAGES),
        });
      }
      if (request.function === "deployment_flows.update_stages") {
        return okEnvelope({
          flow_id: request.payload.flow_id,
          message: "updated",
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountFlows(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/delivery/flows";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

function buttonByText(root, text) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

test("ungated flows do not offer a stage-approval editor", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([UNGATED]));
  assert.equal(buttonByText(root, "Edit who may approve"), undefined);
  assert.equal(byClass(root, "delivery-flow-stage-approvers").length, 0);
  mounted.unmount();
});

test("human-approval stages show who may approve and publish through update_stages",
  async (t) => {
    const client = flowClient([GATED]);
    const { root, mounted } = await mountFlows(t, client);
    assert.equal(
      client.requests.filter(
        (request) => request.function === "workflows.mechanics.get",
      ).length,
      0,
    );
    assert.equal(
      byClass(root, "delivery-flow-stage-approvers")[0].textContent,
      "project operator",
    );
    buttonByText(root, "Edit who may approve").dispatchEvent(new Event("click"));
    await settle();
    assert.equal(
      byClass(root, "workflow-dialog-title")[0].textContent,
      "Stage approvals — Alpha Release",
    );
    assert.equal(
      client.requests.filter(
        (request) => request.function === "workflows.mechanics.get",
      ).length,
      1,
    );
    byClass(root, "workflow-checkbox")[0].children[0]
      .dispatchEvent(new Event("change"));
    buttonByText(root, "Save stage approvals")
      .dispatchEvent(new Event("click"));
    await settle();
    const update = client.requests.find(
      (request) => request.function === "deployment_flows.update_stages",
    );
    assert.equal(update.payload.flow_id, "alpha-release");
    assert.deepEqual(JSON.parse(update.payload.stages)[0].approvals, {
      roles: ["operator", "owner"],
      actors: [],
    });
    assert.equal(JSON.parse(update.payload.stages)[1].step_runner, "auto");
    mounted.unmount();
  },
);
