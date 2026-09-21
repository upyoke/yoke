// Shipping member cards used to keep one answer per item for the run being
// viewed. That hid older screenshots behind a later command check, and it
// painted a pre-merge CI pass as if this release had asked. These cases
// hold the history summary, the always-visible latest pictures, and the
// provenance each check must name for itself.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import {
  activityRow,
  artifact,
  cardFor,
  member,
  memberEntry,
  readingClient,
  RUN_ID,
} from "./universe_ui_carried_item_test_support.mjs";
import {
  checkProvenance,
  historyCaption,
  latestVisualArtifacts,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_member_history.js";

test("latest screenshots survive a later command-only check", () => {
  const visual = activityRow({
    requirement_id: 1,
    happened_at: "2026-09-10T09:00:00Z",
    artifacts: [artifact(10, 1), artifact(11, 1)],
  });
  const command = activityRow({
    requirement_id: 2,
    deployment_run_id: RUN_ID,
    qa_phase: "post_deploy",
    method_id: "command",
    method_name: "Command",
    outcome: "passed",
    happened_at: "2026-09-20T16:00:00Z",
    artifacts: [],
  });
  const latest = latestVisualArtifacts([command, visual]);
  assert.deepEqual(latest.map((row) => row.id), [10, 11]);
  assert.match(historyCaption([command, visual], { runId: RUN_ID }), /verified this release/);
  assert.match(historyCaption([command, visual], { runId: RUN_ID }), /verified before merge/);
});

test("a pre-merge check is not this release's post-deploy answer", () => {
  const ci = activityRow({
    qa_phase: "verification",
    method_id: "command-ci",
    method_name: "Command",
    outcome: "passed",
    artifacts: [],
  });
  const caption = historyCaption([ci], { runId: RUN_ID });
  assert.match(caption, /never asked/);
  assert.doesNotMatch(caption, /verified this release/);
  assert.equal(checkProvenance(ci, { runId: RUN_ID }, [ci]), "verified before merge");
  assert.equal(latestVisualArtifacts([ci]).length, 0);
});

test("collapsed cards keep the latest pictures without expanding history", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [
      activityRow({
        requirement_id: 1,
        qa_phase: "verification",
        happened_at: "2026-09-10T09:00:00Z",
        artifacts: [artifact(10, 1)],
      }),
      activityRow({
        requirement_id: 2,
        deployment_run_id: RUN_ID,
        qa_phase: "post_deploy",
        method_id: "command",
        method_name: "Command",
        outcome: "passed",
        happened_at: "2026-09-20T16:00:00Z",
        artifacts: [],
      }),
    ],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const caption = byClass(evidence, "carried-item-evidence-caption")[0].textContent;
  assert.match(caption, /verified this release/);
  assert.match(caption, /verified before merge/);
  assert.equal(byClass(evidence, "review-shot").length, 1);
  const history = byClass(evidence, "carried-item-history")[0];
  assert.ok(history.hidden, "history starts folded");
  const provenances = byClass(evidence, "carried-item-history-provenance")
    .map((node) => node.getAttribute("data-provenance"));
  assert.ok(provenances.includes("verified against this release"));
  assert.ok(provenances.includes("verified before merge"));
});

test("command-only evidence does not grow fake screenshots", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow({
      deployment_run_id: RUN_ID,
      qa_phase: "post_deploy",
      method_id: "command",
      method_name: "Command",
      outcome: "passed",
      artifacts: [],
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.equal(byClass(evidence, "review-shot").length, 0);
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    /verified this release/,
  );
});
