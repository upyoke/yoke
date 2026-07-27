import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

test("item verification renders current proof with truthful outcome labels", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("blitz");
  item.qa_plan_attachments = [];
  item.qa_requirements = [
    {
      id: 1,
      run_id: 11,
      requirement_source: "welcome-frame",
      plan_slug: "installer-campaign",
      plan_case_key: "welcome-frame",
      method_id: "terminal-inspection",
      method_name: "Terminal inspection",
      outcome: "passed",
      capture_degraded_reason: "image capture blocked on the host",
      proof_summary:
        "text capture + reason — image capture blocked on the host",
      expected_outcome: "Expected welcome prose must not render.",
    },
    {
      id: 2,
      run_id: 12,
      requirement_source: "cold-start-hosted",
      plan_slug: "installer-campaign",
      plan_case_key: "cold-start-hosted @fresh-host",
      method_id: "terminal-check",
      method_name: "Terminal check",
      outcome: "running",
      lease_summary: "Test Mac leased",
      evidence_summary: "transcript + screenshots",
    },
    {
      id: 3,
      run_id: 13,
      requirement_source: "path-on-shell",
      plan_slug: "installer-campaign",
      plan_case_key: "path-on-shell @fresh-host",
      method_id: "machine-state-check",
      method_name: "Machine state check",
      outcome: "blocked_on_precondition",
      proof_summary:
        "baseline unverified yesterday, capability went error; " +
        "rerun queued behind the lease",
    },
    {
      id: 4,
      requirement_source: "not-started",
      method_id: "command",
      method_name: "Command",
      outcome: "queued",
      expected_outcome: "A future expected outcome.",
    },
  ];
  renderItemDetailView(itemContext(documentNode, async (request) => ({
    status: 200,
    envelope: {
      success: true,
      result: request.function === "items.detail.get"
        ? { item }
        : {
          execution: {
            execution_document: {
              slug: "WORKFLOW-TYPES",
              parent_slug: "MASTER-PLAN",
            },
          },
        },
    },
  })), root, "7", "ACM-22");
  await settle();

  const rendered = itemText(root);
  assert.match(
    rendered,
    /Terminal inspection — text capture \+ reason; image capture blocked on the host/,
  );
  assert.match(
    rendered,
    /Terminal check — Test Mac leased · transcript \+ screenshots/,
  );
  assert.match(
    rendered,
    /Machine state check — baseline unverified yesterday, capability went error; rerun queued behind the lease/,
  );
  assert.match(rendered, /Command — not run/);
  assert.doesNotMatch(rendered, /Expected welcome prose/);
  assert.doesNotMatch(rendered, /A future expected outcome/);
  assert.deepEqual(
    byClass(root, "item-proof-row").map(
      (row) => byClass(row, "pill")[0].textContent,
    ),
    [
      "passed · degraded",
      "running",
      "blocked on precondition",
      "queued",
    ],
  );
});

test("Issue union names the gated transition and counts canonical outcomes", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("issue");
  item.qa_plan_attachments = [];
  item.qa_requirements = [
    ["backend-suite", "passed", "exit 0 · output tail"],
    ["changed-path-lint", "passed", "exit 0 · output tail"],
    ["ui-tests", "running", "running in the item worktree"],
  ].map(([caseKey, outcome, proofSummary], index) => ({
    id: index + 1,
    run_id: index + 21,
    plan_case_key: caseKey,
    method_id: "command",
    method_name: "Command",
    outcome,
    proof_summary: proofSummary,
    workflow_transition_id: "reviewed-implementation",
  }));
  renderItemDetailView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: {
      success: true,
      result: { item },
    },
  })), root, "7", "ACM-22");
  await settle();

  const rendered = itemText(root);
  assert.match(rendered, /backend-suite.*exit 0 · output tail/);
  assert.match(rendered, /changed-path-lint.*exit 0 · output tail/);
  assert.match(rendered, /ui-tests.*running in the item worktree/);
  assert.match(
    rendered,
    /2 passed · 1 running; reviewed-implementation waits until every case passes or is waived/,
  );
});

test("item detail exposes a unified-read failure without a legacy retry", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemDetailView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return {
      status: 503,
      envelope: {
        success: false,
        error: { message: "unified detail unavailable" },
      },
    };
  }), root, "7", "ACM-22");
  await settle();

  assert.deepEqual(requests.map((request) => request.function), [
    "items.detail.get",
  ]);
  assert.match(itemText(root), /unified detail unavailable/);
});
