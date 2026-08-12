import assert from "node:assert/strict";
import test from "node:test";

import { renderQaMethodDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_methods.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function visibleText(node) {
  return node.textContent + node.children.map(visibleText).join("");
}

const method = {
  id: "command",
  name: "Command",
  description: "Runs a command in the item worktree.",
  source_kind: "built_in",
  source_ref: null,
  runner_id: "worktree_run",
  required_capability_kind: null,
  verdict_path: "automatic",
  verdict_contract: "exit 0 = pass",
  evidence_contract: "exit code · captured output tail",
  success_policy_id: "all-pass",
  success_policy_params: {},
  concurrency_mode: "parallel",
  used_by_plan_count: 4,
  capability_state: "available",
  capability_context: { state: "available" },
};

const plans = [
  {
    id: 7,
    slug: "release-readiness",
    name: "Release readiness",
    project: "yoke",
    case_keys: ["backend-suite", "changed-path-lint"],
    method_is_complete_plan: false,
    outcome_summary: {
      state: "passed",
      counts: { passed: 2 },
      last_at: "2026-07-27T12:00:00Z",
    },
  },
  {
    id: 8,
    slug: "browser-progress",
    name: "Browser progress",
    project: "yoke",
    case_keys: ["checkout-flow", "signup-smoke"],
    method_is_complete_plan: false,
    outcome_summary: {
      state: "running",
      counts: { passed: 1, queued: 1 },
      last_at: "2026-07-27T12:01:00Z",
    },
  },
  {
    id: 9,
    slug: "visual-review",
    name: "Visual review",
    project: "yoke",
    case_keys: ["marketing-pages-visual"],
    method_is_complete_plan: false,
    outcome_summary: {
      state: "needs_review",
      counts: { needs_review: 1 },
      last_at: "2026-07-27T12:02:00Z",
    },
  },
  {
    id: 10,
    slug: "machine-readiness",
    name: "Machine readiness",
    project: "yoke",
    case_keys: ["path-on-shell"],
    case_summaries: [{
      case_key: "path-on-shell",
      host_baselines: ["fresh-host", "shell-preconfigured"],
    }],
    method_is_complete_plan: false,
    outcome_summary: {
      state: "waiting",
      counts: { waiting: 1 },
      last_at: "2026-07-27T12:03:00Z",
    },
  },
  {
    id: 11,
    slug: "installer-campaign",
    name: "Installer campaign",
    project: "yoke",
    case_keys: ["cold-start-hosted", "hosted-connect", "path-repair"],
    case_summaries: [
      {
        case_key: "cold-start-hosted",
        host_baselines: ["fresh-host", "shell-preconfigured"],
      },
      { case_key: "hosted-connect", host_baselines: [] },
      { case_key: "path-repair", host_baselines: [] },
    ],
    method_is_complete_plan: false,
    outcome_summary: {
      state: "running",
      counts: { running: 1 },
      last_at: "2026-07-27T12:04:00Z",
    },
  },
];


test("method related plans render scoped rollups once across all projects", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const requests = [];
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        requests.push(request);
        return ok({
          method: {
            ...method,
            plans: request.payload.project === "1"
              ? plans
              : [plans[0]],
          },
        });
      },
    },
    projects: () => [
      { id: 1, slug: "yoke", name: "Yoke" },
      { id: 2, slug: "buzz", name: "Buzz" },
    ],
    isMounted: () => true,
  };

  await renderQaMethodDetail(context, host, "all", "command");

  assert.deepEqual(
    requests.map((request) => request.payload.project),
    ["1", "2"],
  );
  assert.equal(byClass(host, "qa-plan-link").length, 5);
  assert.deepEqual(
    byClass(host, "qa-plan-outcome").map(
      (node) => byClass(node, "pill")[0].textContent,
    ),
    ["needs review", "2 passed", "running", "in progress", "waiting"],
  );
  assert.equal(byClass(host, "qa-relative-time").length, 0);
  assert.equal(
    visibleText(byClass(host, "qa-plan-link")[2].children[0].children[1]),
    "cold-start-hosted @fresh-host @shell-preconfigured · " +
      "hosted-connect · path-repair",
  );
  assert.equal(
    visibleText(byClass(host, "qa-plan-link")[4].children[0].children[1]),
    "path-on-shell @fresh-host @shell-preconfigured",
  );
  assert.deepEqual(
    byClass(host, "qa-host-baseline").map((node) => node.textContent),
    [
      "@fresh-host",
      "@shell-preconfigured",
      "@fresh-host",
      "@shell-preconfigured",
    ],
  );
});


test("complete command plans keep ages while a method slice shows its count", async () => {
  const now = Date.now();
  const exactPlans = [
    {
      id: 20,
      slug: "full-verification",
      project: "yoke",
      case_keys: ["backend-suite", "changed-path-lint", "ui-tests"],
      method_is_complete_plan: true,
      outcome_summary: {
        state: "passed",
        counts: { passed: 3 },
        last_at: new Date(now - (2 * 60 * 60 + 5) * 1000).toISOString(),
      },
    },
    {
      id: 21,
      slug: "e2e-suite",
      project: "yoke",
      case_keys: ["e2e"],
      method_is_complete_plan: true,
      outcome_summary: {
        state: "passed",
        counts: { passed: 1 },
        last_at: new Date(now - 26 * 60 * 60 * 1000).toISOString(),
      },
    },
    {
      id: 22,
      slug: "release-readiness",
      project: "yoke",
      case_keys: ["backend-suite", "changed-path-lint"],
      method_is_complete_plan: false,
      outcome_summary: {
        state: "passed",
        counts: { passed: 2 },
        last_at: new Date(now - 30 * 60 * 1000).toISOString(),
      },
    },
  ];
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const context = {
    document: documentNode,
    client: {
      async call() {
        return ok({ method: { ...method, plans: exactPlans } });
      },
    },
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
  };

  await renderQaMethodDetail(context, host, ["1"], "command");

  assert.deepEqual(
    byClass(host, "qa-plan-link").map(
      (node) => node.children[0].children[0].textContent,
    ),
    ["full-verification", "e2e-suite", "release-readiness"],
  );
  assert.deepEqual(
    byClass(host, "qa-plan-outcome").map(
      (node) => byClass(node, "pill")[0].textContent,
    ),
    ["passed", "passed", "2 passed"],
  );
  assert.deepEqual(
    byClass(host, "qa-relative-time").map((node) => node.textContent),
    ["2h ago", "yesterday"],
  );
});


test("test-machine method plan subtitles show counts and bounded case names", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const machineMethod = {
    ...method,
    id: "terminal-check",
    name: "Terminal check",
    required_capability_kind: "test-machine",
    plans: [],
  };
  const context = {
    document: documentNode,
    client: {
      async call() {
        return ok({
          method: {
            ...machineMethod,
            plans: [plans[4]],
          },
        });
      },
    },
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
  };
  const fourCases = {
    ...plans[4],
    case_keys: [...plans[4].case_keys, "project-bootstrap"],
    case_summaries: [
      ...plans[4].case_summaries,
      { case_key: "project-bootstrap", host_baselines: [] },
    ],
  };
  context.client.call = async () => ok({
    method: { ...machineMethod, plans: [fourCases] },
  });

  await renderQaMethodDetail(context, host, ["1"], "terminal-check");

  assert.equal(
    visibleText(byClass(host, "qa-plan-case-summary")[0]),
    "4 cases · cold-start-hosted @fresh-host @shell-preconfigured · " +
      "hosted-connect · path-repair · …",
  );
  assert.deepEqual(
    byClass(host, "qa-key-values")[0].children
      .filter((_, index) => index % 2 === 0)
      .map((node) => node.textContent),
    [
      "Runner",
      "Capability",
      "Verdict",
      "Evidence",
      "Concurrency",
      "Source",
      "Entry surface",
      "Required completion",
    ],
  );
});
