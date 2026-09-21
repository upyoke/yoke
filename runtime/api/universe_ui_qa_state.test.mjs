import assert from "node:assert/strict";
import test from "node:test";

import {
  QA_STATE,
  admittedSourceId,
  classifyMemberQa,
  classifyQaRow,
  memberQaCaption,
  observedReleaseLineage,
  ranAgainstDeployedRevision,
  summarizeQaUnion,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_state.js";

const RUN = "run-20260920-005";

test("admitted copies resolve to their standing source id", () => {
  assert.equal(
    admittedSourceId({ plan_case_key: "admitted-requirement-28759" }),
    28759,
  );
  assert.equal(admittedSourceId({ case_key: "plan-currency-readable" }), null);
});

test("a standing source and its admitted copy are not peers", () => {
  const source = {
    id: 28759,
    item_id: 3449,
    deployment_run_id: null,
    qa_kind: "plan_case",
    qa_phase: "post_deploy",
    plan_case_key: "plan-currency-readable",
    outcome: "queued",
  };
  const copy = {
    id: 28801,
    item_id: null,
    deployment_member_item_id: 3449,
    deployment_run_id: RUN,
    qa_kind: "plan_case",
    qa_phase: "post_deploy",
    plan_case_key: "admitted-requirement-28759",
    outcome: "passed",
  };
  const rows = [source, copy];
  assert.equal(classifyQaRow(source, rows).id, QA_STATE.STANDING_SOURCE);
  assert.match(classifyQaRow(source, rows).detail, /Open is expected/);
  assert.equal(classifyQaRow(copy, rows).id, QA_STATE.ADMITTED_COPY);
  assert.notEqual(
    classifyQaRow(source, rows).label,
    classifyQaRow(copy, rows).label,
  );
});

test("waived, no-obligation, never-asked, and verified stay distinct", () => {
  const waived = classifyQaRow({
    qa_kind: "post_deploy_not_required",
    qa_phase: "post_deploy",
    waived_at: "2026-09-20T16:14:21Z",
    waiver_rationale: "declining it on cost",
  });
  const none = classifyQaRow({
    qa_kind: "post_deploy_no_obligation",
    qa_phase: "post_deploy",
    instructions: "Nothing about this item is observable.",
  });
  const verified = classifyMemberQa([{
    deployment_run_id: RUN,
    qa_kind: "plan_case",
    qa_phase: "post_deploy",
    outcome: "passed",
  }], { runId: RUN });
  const silent = classifyMemberQa([], { runId: RUN });
  const labels = [waived.label, none.label, verified.label, silent.label];
  assert.deepEqual(labels, [
    "waived", "no obligation", "verified this release", "never asked",
  ]);
  assert.equal(new Set(labels).size, 4);
});

test("stage acceptance is run machinery, not the item's own check", () => {
  assert.equal(
    classifyQaRow({ qa_kind: "deployment_stage_acceptance" }).id,
    QA_STATE.RUN_MACHINERY,
  );
  const member = classifyMemberQa([
    {
      deployment_run_id: RUN,
      qa_kind: "plan_case",
      qa_phase: "post_deploy",
      outcome: "passed",
    },
    {
      deployment_run_id: RUN,
      qa_kind: "deployment_stage_acceptance",
      qa_phase: "post_deploy",
      outcome: "passed",
    },
  ], { runId: RUN });
  assert.equal(member.id, QA_STATE.VERIFIED_RUN);
  assert.equal(memberQaCaption(member), "QA · verified this release · 1 passed");
});

test("pre-merge CI does not count as this release's post-deploy answer", () => {
  const member = classifyMemberQa([{
    item_id: 3460,
    deployment_run_id: null,
    qa_kind: "plan_case",
    qa_phase: "verification",
    method_id: "command-ci",
    outcome: "passed",
  }], { runId: RUN });
  assert.equal(member.id, QA_STATE.NEVER_ASKED);
});

test("union discharges superseded and expected standing, and names what still blocks", () => {
  const superseded = summarizeQaUnion([
    {
      id: 1,
      deployment_run_id: RUN,
      qa_kind: "plan_case",
      qa_phase: "post_deploy",
      outcome: "failed",
      superseded_by_requirement_id: 2,
    },
    {
      id: 2,
      deployment_run_id: RUN,
      qa_kind: "method_case",
      qa_phase: "post_deploy",
      outcome: "passed",
    },
  ]);
  assert.equal(superseded.satisfied, true);
  assert.match(superseded.counts, /superseded/);
  assert.equal(superseded.outstandingPhrase, "");

  const standing = summarizeQaUnion([
    {
      id: 10,
      item_id: 100,
      qa_kind: "plan_case",
      qa_phase: "post_deploy",
      plan_case_key: "plan-currency-readable",
      outcome: "queued",
    },
    {
      id: 11,
      deployment_member_item_id: 100,
      deployment_run_id: RUN,
      qa_kind: "plan_case",
      qa_phase: "post_deploy",
      plan_case_key: "admitted-requirement-10",
      outcome: "passed",
    },
  ]);
  assert.equal(standing.satisfied, true);
  assert.match(standing.counts, /source requirement/);

  const blocked = summarizeQaUnion([
    { outcome: "passed", run_id: 1 },
    { outcome: "failed", run_id: 2, deployment_run_id: RUN, qa_phase: "post_deploy" },
  ]);
  assert.equal(blocked.satisfied, false);
  assert.equal(blocked.outstandingPhrase, "1 failed");
});

test("observed lineage prefers the serving SHA over the intended one", () => {
  const sha = "11c1487ec8543ef47c04458bac85a5645382563b";
  const row = {
    execution_target_json: {
      deployment: { release_lineage: "deadbeef" },
      observation: { observed_release_lineage: sha },
    },
  };
  assert.equal(observedReleaseLineage(row), sha);
  assert.equal(ranAgainstDeployedRevision(row, sha), true);
  assert.equal(ranAgainstDeployedRevision(row, "other"), false);
  assert.equal(ranAgainstDeployedRevision({ item_id: 1 }, sha), false);
  assert.equal(
    observedReleaseLineage({
      execution_target_json: { deployment: { release_lineage: sha } },
    }),
    sha,
  );
});

