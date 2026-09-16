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
  documentNode.defaultView.location.hash = "#/deployments/flows";
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

test("a flow with no human-approval stage names no approvers", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([UNGATED]));
  assert.equal(byClass(root, "delivery-flow-stage-approvers").length, 0);
  mounted.unmount();
});

test("human-approval stages name who may approve, and offer no way to change it",
  async (t) => {
    const client = flowClient([GATED]);
    const { root, mounted } = await mountFlows(t, client);

    assert.equal(
      byClass(root, "delivery-flow-stage-approvers")[0].textContent,
      "project operator",
    );
    // A flow definition is authored and versioned by command, and a run
    // freezes the one it referenced. The page that reads a definition offers
    // no control that would rewrite it, and asks for nothing it would need
    // to — the named-approver roster is an editor's read.
    assert.equal(buttonByText(root, "Edit who may approve"), undefined);
    assert.equal(
      client.requests.filter(
        (request) => request.function === "workflows.mechanics.get",
      ).length,
      0,
    );
    assert.equal(
      client.requests.filter(
        (request) => request.function === "deployment_flows.update_stages",
      ).length,
      0,
    );
    mounted.unmount();
  },
);

test("a stage needing every approver reads as and in the pipeline", async (t) => {
  const everyApprover = {
    ...GATED,
    approval_stages: [{
      name: "approve-prod",
      approvals: { roles: ["operator", "owner"], actors: [], mode: "all" },
    }],
  };
  const { root, mounted } = await mountFlows(t, flowClient([everyApprover]));
  assert.equal(
    byClass(root, "delivery-flow-stage-approvers")[0].textContent,
    "project operator and project owner",
  );
  mounted.unmount();
});
