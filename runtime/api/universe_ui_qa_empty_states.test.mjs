import assert from "node:assert/strict";
import test from "node:test";

import {
  renderQaActivity,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import {
  renderQaPlanDetail,
  renderQaPlans,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_plans.js";
import {
  FakeDocument,
  allNodes,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function text(node) {
  return allNodes(node).map((child) => child.textContent).join(" ");
}

function context(documentNode, call) {
  return {
    document: documentNode,
    client: { call },
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate: () => {},
  };
}

test("plan roster, detail, and activity all explain their empty state", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const emptyPlan = {
    id: 12,
    project: "yoke",
    project_id: 1,
    slug: "new-plan",
    name: "New plan",
    description: "",
    success_policy_id: "all-pass",
    success_policy_params: {},
    created_at: "2026-07-26T10:00:00Z",
    updated_at: "2026-07-26T10:00:00Z",
    retired_at: null,
    cases: [],
    attachments: [],
    union: { satisfied: false, counts: {} },
  };
  const uiContext = context(documentNode, async (request) => {
    if (request.function === "qa.plan.list") return ok({ rows: [] });
    if (request.function === "qa.plan.get") return ok({ plan: emptyPlan });
    if (request.function === "qa.activity.list") return ok({ rows: [] });
    throw new Error(`unexpected function ${request.function}`);
  });

  await renderQaPlans(uiContext, host, ["1"]);
  assert.match(text(host), /No test plans in this project scope yet\./);
  assert.match(text(host), /plans and cases are created and edited/);

  await renderQaPlanDetail(uiContext, host, ["1"], "12");
  const detail = text(host);
  assert.match(detail, /No cases declared in this test plan yet\./);
  assert.match(detail, /success policy: no cases declared/);
  assert.match(detail, /not attached yet/);
  assert.match(detail, /No case evidence captured yet\./);
  assert.match(detail, /no runs yet — the plan waits/);

  await renderQaActivity(uiContext, host, ["1"]);
  const activity = text(host);
  assert.match(activity, /0 case runs today/);
  assert.match(activity, /No materialized case activity yet\./);
});

test("a lease-waiting case explains contention without offering actions", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const waitingPlan = {
    id: 13,
    project: "yoke",
    project_id: 1,
    slug: "machine-wait",
    success_policy_id: "all-pass",
    cases: [{
      id: 1,
      case_key: "install-cold-start",
      position: 1,
      method_id: "machine-state-check",
      method_name: "Machine state check",
      required_capability_kind: "test-machine",
      capability_state: "in_use",
      capability_context: {
        state: "in_use",
        wait_reason: "serial_lease_in_use",
        active_lease: { item_ref: "YOK-2001" },
      },
      last_result: {
        requirement_id: 42,
        run_id: 92,
        host_baseline: null,
        outcome: "waiting",
        evidence: [],
      },
    }],
    attachments: [{
      kind: "project_default",
      project: "yoke",
      workflow_id: "issue",
      transition_id: "release",
      transition_label: "Release",
    }],
    union: { satisfied: false, counts: { waiting: 1 } },
  };
  const uiContext = context(
    documentNode,
    async () => ok({ plan: waitingPlan }),
  );

  await renderQaPlanDetail(uiContext, host, ["1"], "13");

  assert.equal(byClass(host, "qa-case-actions")[0].textContent, "—");
  assert.match(
    byClass(host, "pill").find((node) => node.textContent === "in use").title,
    /YOK-2001.*this case queues.*nothing about the plan is blocked/,
  );
  assert.match(
    byClass(host, "pill").find((node) => node.textContent === "waiting").title,
    /required capability or serial lease/,
  );
  assert.match(text(host), /1 waiting — the release transition waits/);
});
