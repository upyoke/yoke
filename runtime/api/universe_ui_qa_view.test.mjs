import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

const methods = [
  {
    id: "command",
    name: "Command",
    description:
      "Run deterministic project commands in a worktree.",
    source_kind: "built_in",
    source_ref: null,
    executor_id: "worktree_run",
    required_capability_kind: null,
    verdict_path: "automatic",
    verdict_contract: "exit 0 = pass",
    evidence_contract: "exit code · captured output tail",
    success_policy_id: "all-pass",
    concurrency_mode: "parallel",
    used_by_plan_count: 2,
    capability_state: "available",
  },
  {
    id: "browser-check",
    name: "Browser check",
    description: "Playwright-style assertions against declared routes.",
    source_kind: "built_in",
    source_ref: null,
    executor_id: "browser_substrate",
    required_capability_kind: "browser-control",
    verdict_path: "automatic",
    verdict_contract: "declared assertions pass",
    evidence_contract: "assertions · trace · logs",
    success_policy_id: "all-pass",
    concurrency_mode: "parallel",
    used_by_plan_count: 1,
    capability_state: "ready",
  },
];

const planRow = {
  id: 7,
  project: "yoke",
  slug: "release-readiness",
  name: "Release readiness",
  description: "",
  case_count: 2,
  materialized_requirement_count: 2,
  method_ids: ["command", "browser-check"],
  attachments: [{
    kind: "project_default",
    project: "yoke",
    workflow_id: "issue",
    transition_id: "release",
    item_id: null,
  }],
  last_outcome: "needs_review",
  last_at: "2026-07-26T12:00:00Z",
};

const planDetail = {
  ...planRow,
  project_id: 1,
  success_policy_id: "all-pass",
  success_policy_params: {},
  created_at: "2026-07-26T10:00:00Z",
  updated_at: "2026-07-26T10:00:00Z",
  retired_at: null,
  cases: [
    {
      id: 1,
      case_key: "backend-suite",
      position: 1,
      method_id: "command",
      method_name: "Command",
      executor_id: "worktree_run",
      required_capability_kind: null,
      verdict_path: "automatic",
      instructions: "Run it.",
      expected_outcome: "It passes.",
      method_config: {},
      success_policy_id: null,
      success_policy_params: null,
      host_baselines: [],
      entry_surface: null,
      required_completion: null,
      last_result: {
        requirement_id: 31,
        run_id: 91,
        outcome: "passed",
        evidence: [{
          id: 4,
          artifact_type: "output",
          content_type: "text/plain",
          artifact_handle: "{\"backend\":\"local\",\"path\":\"output.txt\"}",
          metadata: {},
        }],
      },
    },
    {
      id: 2,
      case_key: "checkout-flow",
      position: 2,
      method_id: "browser-check",
      method_name: "Browser check",
      executor_id: "browser_substrate",
      required_capability_kind: "browser-control",
      verdict_path: "automatic",
      instructions: "Open checkout.",
      expected_outcome: "Confirmation is visible.",
      method_config: {},
      success_policy_id: null,
      success_policy_params: null,
      host_baselines: [],
      entry_surface: null,
      required_completion: null,
      last_result: {
        requirement_id: 32,
        run_id: 92,
        outcome: "needs_review",
        evidence: [],
      },
    },
  ],
  union: { satisfied: false, counts: { passed: 1, needs_review: 1 } },
};

function qaClient() {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "qa.method.list") {
        return ok({ rows: [...methods].reverse() });
      }
      if (request.function === "qa.method.get") {
        return ok({
          method: {
            ...methods.find((row) => row.id === request.payload.method_id),
            plans: [{
              id: 7,
              slug: "release-readiness",
              name: "Release readiness",
              project: "yoke",
              case_keys: ["backend-suite"],
            }],
          },
        });
      }
      if (request.function === "qa.plan.list") return ok({ rows: [planRow] });
      if (request.function === "qa.plan.get") return ok({ plan: planDetail });
      if (request.function === "qa.activity.list") {
        return ok({
          rows: [{
            requirement_id: 32,
            run_id: 92,
            plan_id: 7,
            plan: "release-readiness",
            project: "yoke",
            case_key: "checkout-flow",
            host_baseline: null,
            method_id: "browser-check",
            method_name: "Browser check",
            outcome: "needs_review",
            evidence_count: 4,
            capture_degraded_reason: null,
            happened_at: new Date().toISOString(),
          }],
        });
      }
      if (request.function === "qa.artifact.read") {
        return ok({
          artifact_id: 4,
          backend: "local",
          disposition: "ready",
          content_type: "text/plain",
          content_base64: "ZnVsbCBvdXRwdXQ=",
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountAt(t, hash) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const client = qaClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, client, mounted };
}

test("QA defaults to the prototype Methods roster and opens contract detail", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa?project=1",
  );

  assert.deepEqual(
    byClass(root, "tab-link").map((node) => node.textContent),
    ["Methods", "Plans", "Activity"],
  );
  assert.equal(byClass(root, "qa-method-card").length, 2);
  assert.deepEqual(
    byClass(root, "qa-method-card").map(
      (node) => byClass(node, "qa-method-identity")[0].children[0].textContent,
    ),
    ["Command", "Browser check"],
  );
  const text = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(
    text,
    /Test plans prove the work; methods say how; capabilities make it possible/,
  );
  assert.match(text, /requires nothing — a checkout is enough/);
  assert.match(text, /requires Browser control · ready/);
  assert.match(text, /How methods enter this project/);
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.method.list"),
    { function: "qa.method.list", payload: { project: "1" } },
  );

  byClass(root, "qa-method-card")[0].dispatchEvent(new Event("click"));
  await settle();
  const detailText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(detailText, /Contract/);
  assert.match(detailText, /worktree_run/);
  assert.match(detailText, /Used by plans/);
  assert.match(detailText, /release-readiness/);
  mounted.unmount();
});

test("Plans renders the durable objects and the full case-detail composition", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa/plans?project=1",
  );

  assert.equal(byClass(root, "qa-plans-table").length, 1);
  const listText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(listText, /release-readiness/);
  assert.match(listText, /project default · release/);
  assert.match(listText, /needs review/);

  byClass(root, "qa-plan-button")[0].dispatchEvent(new Event("click"));
  await settle();
  const detailText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(detailText, /Case sequence/);
  assert.match(detailText, /backend-suite/);
  assert.match(detailText, /checkout-flow/);
  assert.match(detailText, /union gate not satisfied/);
  assert.match(detailText, /Attached to/);
  assert.match(detailText, /Evidence/);
  assert.match(detailText, /output.txt/);
  assert.match(
    detailText,
    /yoke qa plan-cases replace --project yoke --plan-id 7 --stdin/,
  );
  byClass(root, "qa-evidence-open")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.match(
    allNodes(root).map((node) => node.textContent).join(" "),
    /Open evidence/,
  );
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.artifact.read"),
    {
      function: "qa.artifact.read",
      payload: { artifact_id: 4 },
      target: { kind: "qa_requirement", qa_requirement_id: 31 },
    },
  );
  mounted.unmount();
});

test("Activity folds hidden QA plumbing into readable outcomes", async (t) => {
  const { root, mounted } = await mountAt(
    t, "#/qa/activity?project=1",
  );

  assert.equal(byClass(root, "qa-stat").length, 4);
  const text = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(text, /case runs today/);
  assert.match(text, /release-readiness/);
  assert.match(text, /checkout-flow/);
  assert.match(text, /Browser check/);
  assert.match(text, /needs review/);
  assert.match(text, /4 artifacts/);
  assert.match(text, /Blocked on precondition is neither a pass/);
  mounted.unmount();
});
