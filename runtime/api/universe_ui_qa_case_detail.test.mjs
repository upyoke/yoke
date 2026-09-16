// The QA case page an Activity row opens: what the case had to prove, which
// subject it answers for, the stage execution that judged it, and what it
// captured.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderQaCaseDetail,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_qa.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const REQUIREMENT = {
  id: 9001,
  item_id: 2262,
  deployment_run_id: "run-20260726-001",
  deployment_stage: "stage-item-qa",
  deployment_member_item_id: 2262,
  plan_id: 7,
  plan_case_key: "preview-url-compare",
  method_id: "browser-check",
  method_name: "Browser check",
  target_env: "stage",
  verdict_path: "agent",
  instructions: "Open the stage preview and compare the release banner.",
  expected_outcome: "The banner names the candidate revision.",
  waived_at: null,
  waiver_rationale: null,
};

// The case's own executions, which the run list serves complete. The activity
// table joins a requirement to its latest run alone, so the page reads this
// rather than trusting a page of recent activity to carry the case at all.
const EXECUTION = {
  id: 44,
  qa_requirement_id: 9001,
  performed_by: "browser",
  verdict: "fail",
  case_outcome: "failed",
  execution_status: "captured",
  verdict_reason: "The banner named the previous revision.",
  capture_degraded_reason: null,
  created_at: "2026-07-26T10:05:00Z",
  completed_at: "2026-07-26T10:05:00Z",
};

const ACTIVITY_ROW = {
  requirement_id: 9001,
  run_id: 44,
  deployment_run_id: "run-20260726-001",
  deployment_stage: "stage-item-qa",
  item_id: 2262,
  plan_id: 7,
  plan: "release-readiness",
  project: "yoke",
  case_key: "preview-url-compare",
  method_id: "browser-check",
  method_name: "Browser check",
  outcome: "failed",
  verdict_reason: "The banner named the previous revision.",
  capture_degraded_reason: null,
  precondition_reason: null,
  evidence_count: 1,
  artifacts: [{ id: 17624, artifact_type: "screenshot", content_type: "image/png" }],
  happened_at: "2026-07-26T10:05:00Z",
};

function caseContext(documentNode, requests, overrides = {}) {
  return {
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate: () => {},
    client: {
      async call(request) {
        requests.push(request);
        if (request.function === "qa.requirement.get") {
          return ok({
            requirement: overrides.requirement ?? REQUIREMENT,
          });
        }
        if (request.function === "qa.activity.list") {
          return ok({ rows: overrides.rows ?? [ACTIVITY_ROW] });
        }
        if (request.function === "qa.run.list") {
          return ok({ rows: overrides.runs ?? [EXECUTION] });
        }
        if (request.function === "deployment_runs.stages") {
          return ok({
            run_id: "run-20260726-001",
            flow: "yoke-stage-then-prod",
            status: "executing",
            current_stage: "stage-item-qa",
            stages: [{
              name: "stage-item-qa",
              scope: "item",
              verdict: { mode: "required_human", reviewers: {} },
              state: "current",
              position: 2,
            }],
          });
        }
        if (request.function === "items.detail.get") {
          return ok({
            item: {
              id: 2262, public_ref: "YOK-2228", title: "Ship the release",
              project: { id: 1, slug: "yoke" },
            },
          });
        }
        if (request.function === "inbox.list") {
          return ok({ needs_decision: overrides.needs_decision ?? [] });
        }
        if (request.function === "qa.artifact.read") {
          return ok({
            artifact_id: request.payload.artifact_id, disposition: "ready",
            content_type: "image/png", content_base64: "aVZCT1J3MEs=",
          });
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    },
  };
}

function values(root) {
  return allNodes(root)
    .filter((node) => node.tagName === "DD")
    .map((node) => node.textContent);
}

test("a case page names its subject, its stage execution, and its contract", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const requests = [];
  await renderQaCaseDetail(caseContext(documentNode, requests), root, "1", "9001");
  await settle();

  // The case is read by its own id; the row it draws is found through the
  // subject the case names, because activity is keyed by subject.
  const definition = requests.find((r) => r.function === "qa.requirement.get");
  assert.deepEqual(definition.target, {
    kind: "qa_requirement", qa_requirement_id: 9001,
  });
  assert.deepEqual(
    requests.find((r) => r.function === "qa.activity.list").payload,
    { project: "1", item_ids: [2262] },
  );

  assert.equal(byClass(root, "title")[0].textContent, "preview-url-compare");
  const facts = values(root);
  // Subject is the item's public ref, not the internal id the case stores.
  assert.match(facts[0], /YOK-2228/);
  assert.equal(facts[1], "item");
  assert.equal(facts[2], "stage");
  // The verdict policy is attributed to the stage that set it.
  assert.match(facts[3], /run-20260726-001 · stage-item-qa/);
  assert.match(facts[3], /verdict required human \(set by this stage\)/);
  assert.equal(facts[4], "Browser check");
  assert.equal(facts[5], "failed");
  // The contract the case was held to, and what the agent said about it.
  assert.match(facts[7], /Open the stage preview/);
  assert.match(facts[8], /banner names the candidate revision/);
  assert.match(
    byClass(root, "qa-case-reason")[0].textContent,
    /What the agent said: The banner named the previous revision\./,
  );
  assert.equal(byClass(root, "review-shot").length, 1);
});

test("a repeated case keeps its history instead of only its newest run", async () => {
  // The activity table joins a requirement to its latest run alone, so a case
  // run twice would otherwise look like it ran once.
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const requests = [];
  await renderQaCaseDetail(
    caseContext(documentNode, requests, {
      runs: [
        { ...EXECUTION, id: 51, verdict: "pass", case_outcome: "passed",
          verdict_reason: null, completed_at: "2026-07-26T12:00:00Z" },
        { ...EXECUTION, id: 44 },
      ],
    }),
    root, "1", "9001",
  );
  await settle();

  // The complete run list is read by requirement, not by subject recency.
  assert.deepEqual(
    requests.find((r) => r.function === "qa.run.list").payload,
    { requirement_id: 9001 },
  );
  const facts = values(root);
  // Newest execution is the current answer; the earlier one is still counted.
  assert.equal(facts[5], "passed");
  assert.equal(facts[7], "1 before this one");
});

test("an execution whose evidence is out of reach does not read as never run", async () => {
  // A case whose subject the activity read does not carry still ran; saying
  // "never run" there would deny an execution the run list can see.
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  await renderQaCaseDetail(
    caseContext(documentNode, [], { rows: [] }), root, "1", "9001",
  );
  await settle();

  const facts = values(root);
  assert.equal(facts[5], "failed");
  assert.notEqual(facts[6], "never run");
  assert.match(
    byClass(root, "empty")[0].textContent,
    /evidence could not be resolved/,
  );
});

test("a case that truly never ran says so", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  await renderQaCaseDetail(
    caseContext(documentNode, [], { runs: [], rows: [] }), root, "1", "9001",
  );
  await settle();

  const facts = values(root);
  assert.equal(facts[5], "never run");
  assert.equal(facts[6], "never run");
});

test("a standalone case keeps its own subject rather than borrowing a release", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const requests = [];
  const context = caseContext(documentNode, requests, {
    requirement: {
      ...REQUIREMENT,
      item_id: null,
      deployment_run_id: null,
      deployment_stage: null,
      deployment_member_item_id: null,
    },
    rows: [{
      ...ACTIVITY_ROW,
      item_id: null, deployment_run_id: null, deployment_stage: null,
      outcome: "passed", verdict_reason: null, artifacts: [],
    }],
  });
  await renderQaCaseDetail(context, root, "1", "9001");
  await settle();

  const facts = values(root);
  assert.equal(facts[0], "standalone — not bound to an item or a release");
  assert.equal(facts[1], "standalone");
  assert.equal(facts[3], "not part of a release");
  // No release means no stage read to make.
  assert.equal(
    requests.filter((r) => r.function === "deployment_runs.stages").length, 0,
  );
});

test("a case still waiting on a person carries that decision", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const requests = [];
  const context = caseContext(documentNode, requests, {
    needs_decision: [{
      id: 5150,
      kind: "qa_needs_review",
      status: "pending",
      project_id: 1,
      subject_context: { requirement_id: 9001 },
      actions: ["reject", "approve"],
      deciders: [],
      can_act: true,
      decided_by_you: false,
      your_decision: null,
    }],
  });
  await renderQaCaseDetail(context, root, "1", "9001");
  await settle();

  assert.equal(byClass(root, "qa-case-review").length, 1);
  assert.deepEqual(
    byClass(root, "review-action").map((node) => node.textContent),
    ["Reject", "Approve"],
  );
});
