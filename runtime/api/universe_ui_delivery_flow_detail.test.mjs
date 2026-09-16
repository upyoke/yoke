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
  stages: STAGES,
};

const UNGATED = {
  ...GATED,
  id: "alpha-build", name: "Alpha Build",
  stages: [
    { name: "build", step_runner: "auto" },
    { name: "verify", step_runner: "auto" },
  ],
};

// A QA stage carries the whole vocabulary a release is held to: what it
// checks, where, who rules on it, and who is only told the outcome.
const SCOPED = {
  ...GATED,
  id: "alpha-preview", name: "Alpha Preview",
  target_tier: "ephemeral", target_environment: null,
  stages: [
    {
      name: "preview-deploy",
      step_runner: "ephemeral-deploy",
      stage_kind: "execution",
      target: { kind: "run_preview", capability: "ephemeral-env" },
    },
    {
      name: "item-qa",
      step_runner: "qa",
      stage_kind: "qa",
      scope: "item",
      target: { kind: "run_preview", source_stage: "preview-deploy" },
      cases: { plan_id: 7, case_keys: ["preview-url-compare"] },
      verdict: {
        mode: "required_human",
        reviewers: { roles: ["owner"], actors: [], mode: "any" },
      },
      notification: { enabled: true, recipients: { item_owners: true } },
    },
    {
      name: "release-qa",
      step_runner: "qa",
      stage_kind: "qa",
      scope: "run",
      target: {
        kind: "persistent_environment",
        environment: "stage",
        source_stage: "stage-deploy",
      },
      cases: { plan_id: 9 },
      verdict: { mode: "agent_only" },
      notification: {
        enabled: true,
        recipients: { roles: ["operator"], actors: [] },
      },
    },
  ],
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

// One stage card's policy rows as label -> value, which is how a reader
// takes the card in.
function policyFor(root, index) {
  const card = byClass(root, "delivery-flow-stage")[index];
  const rows = byClass(card, "delivery-flow-stage-policy-row");
  return Object.fromEntries(rows.map((row) => [
    row.children[0].textContent,
    row.children[1].textContent,
  ]));
}

test("a flow with no human-approval stage names no approvers", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([UNGATED]));
  assert.equal(policyFor(root, 0).Approval, undefined);
  mounted.unmount();
});

test("human-approval stages name who may approve, and offer no way to change it",
  async (t) => {
    const client = flowClient([GATED]);
    const { root, mounted } = await mountFlows(t, client);

    assert.equal(policyFor(root, 0).Approval, "project operator");
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
    stages: [
      {
        ...STAGES[0],
        approvals: { roles: ["operator", "owner"], actors: [], mode: "all" },
      },
      STAGES[1],
    ],
  };
  const { root, mounted } = await mountFlows(t, flowClient([everyApprover]));
  assert.equal(
    policyFor(root, 0).Approval,
    "project operator and project owner",
  );
  mounted.unmount();
});

test("an item-scoped QA stage says what it checks and who rules on it",
  async (t) => {
    const { root, mounted } = await mountFlows(t, flowClient([SCOPED]));

    assert.deepEqual(
      byClass(root, "delivery-flow-stage-kind").map((node) => node.textContent),
      ["ephemeral-deploy", "QA", "QA"],
    );
    const item = policyFor(root, 1);
    assert.equal(item.Scope, "runs once per admitted item");
    // The preview has no name to look up, so it is named by its builder.
    assert.equal(item["Runs on"], "the preview preview-deploy built");
    assert.equal(item.Cases, "plan 7 · preview-url-compare");
    assert.equal(item.Verdict, "a person decides, always — project owner");
    assert.equal(item.Notify, "each item's owner");
    mounted.unmount();
  },
);

test("a run-scoped QA stage separates deciding from being told", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([SCOPED]));

  const release = policyFor(root, 2);
  assert.equal(release.Scope, "runs once for the whole release");
  assert.equal(release["Runs on"], "stage environment, as stage-deploy left it");
  assert.equal(release.Cases, "plan 9 · every case in the plan");
  // agent_only carries no reviewers; the operator is on the notice list and
  // reading that as authority is exactly the confusion the two lines prevent.
  assert.equal(release.Verdict, "the agent decides");
  assert.equal(release.Notify, "project operator");
  mounted.unmount();
});

test("a stage the definition gave no policy shows none", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([UNGATED]));
  assert.deepEqual(policyFor(root, 1), {});
  assert.equal(byClass(root, "delivery-flow-stage-name")[1].textContent, "verify");
  mounted.unmount();
});
