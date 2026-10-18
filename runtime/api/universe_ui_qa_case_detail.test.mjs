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

const REQUIREMENT = { id: 9001,
  public_ref: "YOK-2228",
  deployment_run_id: "run-20260726-001",
  deployment_stage: "stage-item-qa",
  deployment_member_public_ref: "YOK-2228",
  plan_id: 7,
  plan_case_key: "preview-url-compare",
  method_id: "browser-check",
  method_name: "Browser check",
  target_env: null,
  execution_environment: "demo-preview",
  execution_candidate_revision: "aa11bb22cc33dd44ee55ff6677889900aabbccdd",
  verdict_path: "agent",
  instructions: "Open the stage preview and compare the release banner.",
  expected_outcome: "The banner names the candidate revision.",
  waived_at: null,
  waiver_rationale: null,
};

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
  public_ref: "YOK-2228",
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
          return ok({ rows: overrides.runs ?? [EXECUTION],
            ...(overrides.legacy ? {} : { current_run_id: overrides.currentId
              ?? (overrides.runs === undefined ? 44 : overrides.runs[0]?.id ?? null) }) });
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
              public_ref: "YOK-2228", title: "Ship the release",
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

  const definition = requests.find((r) => r.function === "qa.requirement.get");
  assert.deepEqual(definition.target, {
    kind: "qa_requirement", qa_requirement_id: 9001,
  });
  assert.deepEqual(
    requests.find((r) => r.function === "qa.activity.list").payload,
    { project: "1", public_refs: ["YOK-2228"] },
  );

  assert.equal(byClass(root, "title")[0].textContent, "Browser check · YOK-2228");
  const facts = values(root);
  assert.match(facts[0], /YOK-2228/);
  assert.equal(facts[1], "item");
  assert.equal(facts[2], "demo-preview");
  assert.match(facts[3], /run-20260726-001 · stage-item-qa/);
  assert.match(facts[3], /verdict required human \(set by this stage\)/);
  assert.equal(facts[4], "Browser check");
  assert.equal(facts[5], "failed");
  assert.equal(facts[7], "aa11bb22cc33dd44ee55ff6677889900aabbccdd");
  assert.match(facts[8], /Open the stage preview/);
  assert.match(facts[9], /banner names the candidate revision/);
  assert.match(
    byClass(root, "qa-case-reason")[0].textContent,
    /What the agent said: The banner named the previous revision\./,
  );
  assert.equal(byClass(root, "review-shot").length, 1);
});

test("a repeated case keeps its history instead of only its newest run", async () => {
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

  assert.deepEqual(
    requests.find((r) => r.function === "qa.run.list").payload,
    { requirement_id: 9001 },
  );
  const facts = values(root);
  assert.equal(facts[5], "passed");
  assert.equal(facts[7], "1 before this one");
});

test("case detail preserves native current-attempt selection across offset and tie ordering", async () => {
  for (const currentId of [6, 7]) {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("main");
    // A detached review has the largest id; native start/id selection names
    // the actual attempt even when its row appears last in returned history.
    const runs = [
      { ...EXECUTION, id: currentId, verdict: "pass", case_outcome: "passed",
        started_at: "2026-10-01T09:00:01+09:00", created_at: "2026-09-30T00:00:00Z" },
      { ...EXECUTION, id: currentId === 6 ? 7 : 6, verdict: null,
        case_outcome: "needs_review", started_at: currentId === 6
          ? "2026-09-30T20:00:00-04:00" : "2026-09-30T20:00:01-04:00" },
      { ...EXECUTION, id: 99, performed_by: "agent", case_outcome: "failed" },
    ];
    await renderQaCaseDetail(caseContext(documentNode, [], {
      runs: [runs[2], runs[1], runs[0]], currentId,
    }), root, "1", "9001");
    await settle();
    assert.equal(values(root)[5], "passed");
    assert.equal(values(root)[7], "2 before this one");
  }
});

test("an execution whose evidence is out of reach does not read as never run", async () => {
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

test("case detail displays the native judged outcome over retained capture evidence", async () => {
  for (const [verdict, caseOutcome] of [["pass", "passed"], ["fail", "failed"], ["undetermined", "needs_review"]]) {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("main");
    const run = { ...EXECUTION, verdict, case_outcome: caseOutcome,
      raw_result: JSON.stringify({ case_outcome: "needs_review", evidence: "saved frame" }),
      execution_status: "captured" };
    await renderQaCaseDetail(caseContext(documentNode, [], { runs: [run] }), root, "1", "9001");
    await settle();
    assert.equal(values(root)[5], caseOutcome === "needs_review" ? "needs review" : caseOutcome);
  }
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
      public_ref: null,
      deployment_run_id: null,
      deployment_stage: null,
      deployment_member_public_ref: null,
    },
    rows: [{
      ...ACTIVITY_ROW,
      public_ref: null, deployment_run_id: null, deployment_stage: null,
      outcome: "passed", verdict_reason: null, artifacts: [],
    }],
  });
  await renderQaCaseDetail(context, root, "1", "9001");
  await settle();

  const facts = values(root);
  assert.equal(facts[0], "standalone — not bound to an item or a release");
  assert.equal(facts[1], "standalone");
  assert.equal(facts[3], "not part of a release");
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

test("missing current identity names the serving floor and recovery", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("main");
  await renderQaCaseDetail(caseContext(doc, [], { legacy: true }), root, "1", "9001");
  assert.match(root.textContent, /qa_current_run_identity_unavailable/);
  assert.match(root.textContent, /response floor/);
  assert.match(root.textContent, /control-plane operator/);
});

test("a selected run absent from history refuses instead of saying never run", async () => {
  const doc = new FakeDocument();
  const root = doc.createElement("main");
  await renderQaCaseDetail(caseContext(doc, [], { runs: [], currentId: 99 }), root, "1", "9001");
  assert.match(root.textContent, /qa_current_run_identity_unavailable/);
  assert.doesNotMatch(root.textContent, /never run/);
});
