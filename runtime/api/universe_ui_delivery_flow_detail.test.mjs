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
    approvals: { roles: [], actors: [2], mode: "any" },
  },
  { name: "release", step_runner: "auto" },
  { name: "ship", step_runner: "github-actions-workflow", workflow: "release.yml" },
  { name: "warm", step_runner: "warm-up", connection_env: "prod" },
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
        return okEnvelope({ flows, flow_actor_names: { 2: "Ben Bauman" } });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({ rows: [] });
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

function stageFacts(root, index) {
  const stage = byClass(root, "delivery-flow-stage")[index];
  const list = byClass(stage, "delivery-flow-stage-facts")[0];
  if (!list) return {};
  const cells = list.children;
  const facts = {};
  for (let at = 0; at < cells.length; at += 2) {
    facts[cells[at].textContent] = cells[at + 1].textContent;
  }
  return facts;
}

function stageText(root, className) {
  return byClass(root, className).map((node) => node.textContent);
}

test("the pipeline is a numbered rail naming what runs each stage", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([GATED]));
  assert.deepEqual(stageText(root, "delivery-flow-stage-num"), ["1", "2", "3", "4"]);
  assert.deepEqual(stageText(root, "delivery-flow-stage-name"), ["approve-prod", "release", "ship", "warm"]);
  assert.deepEqual(stageText(root, "delivery-flow-stage-kind"), [
    "Approval", "Automatic", "GitHub Actions · release.yml", "Warm-up · prod",
  ]);
  mounted.unmount();
});

test("an approval stage is person-decided and names its approvers by name", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([GATED]));
  const stage = byClass(root, "delivery-flow-stage")[0];
  assert.equal(stage.classList.contains("is-person"), true);
  assert.equal(byClass(stage, "delivery-flow-stage-person")[0].textContent, "a person decides");
  assert.deepEqual(stageFacts(root, 0), { Approvers: "Ben Bauman" });
  assert.deepEqual(stageFacts(root, 1), {});
  mounted.unmount();
});

test("a flow without approval stages marks no stage as person-decided", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([UNGATED]));
  assert.equal(byClass(root, "is-person").length, 0);
  assert.equal(byClass(root, "delivery-flow-stage-facts").length, 0);
  mounted.unmount();
});

test("QA stages say scope, where they run, cases and who decides in plain words", async (t) => {
  const { root, mounted } = await mountFlows(t, flowClient([SCOPED]));
  assert.deepEqual(stageFacts(root, 0), { "Runs on": "a per-run preview (ephemeral-env)" });
  assert.deepEqual(stageFacts(root, 1), {
    Scope: "runs once per admitted item",
    "Runs on": "the preview preview-deploy built",
    Cases: "plan 7 · preview-url-compare",
    Verdict: "a person decides — project owner",
    Notify: "each item's owner",
  });
  assert.equal(byClass(root, "delivery-flow-stage")[1].classList.contains("is-person"), true);
  const release = stageFacts(root, 2);
  assert.equal(release.Scope, "runs once for the whole release");
  assert.equal(release["Runs on"], "stage environment, as stage-deploy left it");
  assert.equal(release.Verdict, "the agent decides");
  assert.equal(byClass(root, "delivery-flow-stage")[2].classList.contains("is-qa"), true);
  assert.deepEqual(stageText(root, "delivery-flow-stage-kind"), ["Preview deploy", "QA", "QA"]);
  mounted.unmount();
});
