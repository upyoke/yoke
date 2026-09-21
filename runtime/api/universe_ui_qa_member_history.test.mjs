// Shipping member cards used to keep one answer per item for the run being
// viewed. That hid older screenshots behind a later command check, and it
// painted a pre-merge CI pass as if this release had asked. These cases
// hold the history summary, the always-visible latest pictures, and the
// provenance each check must name for itself.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import {
  activityRow,
  artifact,
  cardFor,
  deployedTarget,
  DEPLOYED_SHA,
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

const AGAINST_DEPLOYED = "ran against the deployed revision";
const NOT_DEPLOYED = "not the revision that is deployed";

test("folded history stays hidden against its own flex layout", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/qa_member_history.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.carried-item-history\[hidden\] \{[^}]*display: none;/,
  );
});

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
    execution_target_json: deployedTarget(),
  });
  const latest = latestVisualArtifacts([command, visual], { deployedSha: DEPLOYED_SHA });
  assert.deepEqual(latest.map((row) => row.id), [10, 11]);
  assert.match(
    historyCaption([command, visual], { runId: RUN_ID, deployedSha: DEPLOYED_SHA }),
    new RegExp(AGAINST_DEPLOYED),
  );
  assert.match(
    historyCaption([command, visual], { runId: RUN_ID, deployedSha: DEPLOYED_SHA }),
    /verified before merge/,
  );
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
        execution_target_json: deployedTarget(),
      }),
    ],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const caption = byClass(evidence, "carried-item-evidence-caption")[0].textContent;
  assert.match(caption, new RegExp(AGAINST_DEPLOYED));
  assert.match(caption, /verified before merge/);
  assert.equal(byClass(evidence, "review-shot").length, 1);
  assert.match(
    byClass(evidence, "review-evidence")[0].className,
    /\bcompact\b/,
  );
  const history = byClass(evidence, "carried-item-history")[0];
  assert.ok(history.hidden, "history starts folded");
  const provenances = byClass(evidence, "carried-item-history-provenance")
    .map((node) => node.getAttribute("data-provenance"));
  assert.ok(provenances.includes(AGAINST_DEPLOYED));
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
      execution_target_json: deployedTarget(),
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.equal(byClass(evidence, "review-shot").length, 0);
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    new RegExp(AGAINST_DEPLOYED),
  );
});

test("intake-source screenshots do not read as the deployed revision", async () => {
  const standing = activityRow({
    id: 29205,
    qa_phase: "post_deploy",
    outcome: "queued",
    artifacts: [artifact(10, 26134)],
  });
  const options = { runId: RUN_ID, deployedSha: DEPLOYED_SHA };
  assert.equal(checkProvenance(standing, options, [standing]), NOT_DEPLOYED);
  assert.match(historyCaption([standing], options), new RegExp(NOT_DEPLOYED));
  assert.equal(
    latestVisualArtifacts([standing], options)[0].provenance,
    NOT_DEPLOYED,
  );

  const documentNode = new FakeDocument();
  const client = readingClient({ rows: [standing] });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();
  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    new RegExp(NOT_DEPLOYED),
  );
  const shot = byClass(evidence, "review-shot")[0];
  assert.equal(shot.getAttribute("data-provenance"), NOT_DEPLOYED);
  assert.match(shot.textContent, new RegExp(NOT_DEPLOYED));
});

test("another release's checks do not replace this run's never-asked caption", () => {
  const other = activityRow({ deployment_run_id: "run-20260910-003" });
  const options = { runId: RUN_ID, deployedSha: DEPLOYED_SHA };
  assert.equal(checkProvenance(other, options, [other]), NOT_DEPLOYED);
  const caption = historyCaption([other], options);
  assert.match(caption, /never asked/);
  assert.doesNotMatch(caption, new RegExp(NOT_DEPLOYED));
});
