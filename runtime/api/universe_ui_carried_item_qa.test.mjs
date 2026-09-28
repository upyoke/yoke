// A carried item's QA inside its run entry is an "Item QA" section drawn
// exactly like "Run QA": the checks this run recorded (or, failing those,
// the one that ran against the deployed revision) lead with their own
// screenshots, and every other check is one line behind a single "Earlier
// checks" disclosure, each linking its own QA case and its run or CI run.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument } from "./universe_ui_dom_test_support.mjs";
import {
  artifact,
  DEPLOYED_SHA,
  deployedTarget,
  RUN_ID,
} from "./universe_ui_carried_item_test_support.mjs";
import { readArtifact } from "../../packages/yoke-core/src/yoke_core/ui/static/review_evidence_read.js";
import { itemQaChecks } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_qa.js";
import {
  appendCarriedItemHeading,
  loadMissingItemTitles,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_titles.js";
import { qaScopeSection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_qa_checks.js";

const CI_URL = "https://github.com/upyoke/platform/actions/runs/1234";
const OLDER_RUN = "run-20260910-002";

function check(overrides) {
  return {
    requirement_id: 1, project: "yoke", deployment_run_id: null, qa_phase: "",
    qa_kind: "plan_case", method_name: "Command", outcome: "passed", artifacts: [],
    happened_at: "2026-09-10T09:00:00Z", ...overrides,
  };
}

const history = [
  check({ requirement_id: 11, qa_phase: "verification", run_url: CI_URL,
    method_name: "Command (CI)", happened_at: "2026-09-09T09:00:00Z" }),
  check({ requirement_id: 12, deployment_run_id: OLDER_RUN, qa_phase: "post_deploy",
    method_name: "Browser inspection", execution_target_json: deployedTarget("0ld"),
    artifacts: [artifact(40, 12)],
    happened_at: "2026-09-10T08:00:00Z" }),
  check({ requirement_id: 13, deployment_run_id: OLDER_RUN, qa_phase: "post_deploy",
    outcome: "failed", execution_target_json: deployedTarget("0ld"),
    happened_at: "2026-09-10T07:00:00Z" }),
  check({ requirement_id: 14, deployment_run_id: RUN_ID, qa_phase: "post_deploy",
    execution_target_json: deployedTarget(DEPLOYED_SHA),
    artifacts: [
      { id: 90, artifact_type: "command_output", content_type: "text/plain" },
      ...[1, 2, 3, 4, 5, 6, 7].map((id) => artifact(id, 14)),
    ],
    happened_at: "2026-09-10T10:00:00Z" }),
];

function paint(rows = history) {
  const documentNode = new FakeDocument();
  const context = { document: documentNode, projects: () => [{ id: 1, slug: "yoke" }],
    client: { call: async () => ({ status: 200, envelope: { success: true, result: {} } }) } };
  const scoped = itemQaChecks(rows, { runId: RUN_ID, deployedSha: DEPLOYED_SHA });
  return qaScopeSection(context, { heading: "Item QA", ...scoped, runId: RUN_ID, project: 1 });
}

const checkLines = (host) => host.children.filter(
  (node) => node.classList.contains("run-qa-check"));

test("the check this run recorded leads, then earlier checks", () => {
  const section = paint();
  const classes = section.children.map((node) => node.className.split(" ")[0]);
  assert.deepEqual(classes, ["run-qa-head", "run-qa-check", "run-qa-history"]);
  assert.equal(section.children[0].children[0].textContent, "Item QA");
  assert.equal(section.children[0].children[1].textContent, "1 of 1 passed");
  const current = section.children[1];
  assert.equal(byClass(current, "run-qa-check-mark")[0].textContent, "✓");
  assert.equal(byClass(current, "run-qa-check-name")[0].children[0].href,
    "#/qa-activity/14?project=1");
  assert.equal(byClass(current, "run-qa-check-outcome")[0].textContent, "Passed");
  // The output is its own chip in the check's strip.
  assert.equal(byClass(current, "review-text-chip").length, 1);
});

test("a check's screenshots open and close the rest in place", () => {
  const strip = byClass(paint().children[1], "review-evidence")[0];
  assert.equal(byClass(strip, "review-shot").length, 5);
  const more = byClass(strip, "review-more")[0];
  assert.equal(more.textContent, "and 2 more");
  more.dispatchEvent(new Event("click"));
  assert.equal(byClass(strip, "review-shot").length, 7);
});

test("every other check is one line behind one Earlier checks disclosure", () => {
  const earlier = byClass(paint(), "run-qa-history")[0];
  assert.equal(earlier.tagName, "DETAILS");
  assert.equal(earlier.children[0].textContent, "Earlier checks (3)");
  const rows = checkLines(earlier);
  assert.equal(rows.length, 3);
  // Newest first: an older release's pass, its failure, then before merge.
  assert.equal(byClass(rows[0], "run-qa-check-outcome")[0].textContent, "Passed");
  const runLink = byClass(rows[0], "run-qa-check-run")[0];
  assert.equal(runLink.textContent, "Run 20260910-002");
  assert.equal(runLink.href, `#/deployments/runs/${OLDER_RUN}?project=1`);
  assert.equal(byClass(rows[0], "run-qa-check-name")[0].children[0].href,
    "#/qa-activity/12?project=1");
  // Each earlier check keeps the screenshots it captured under itself.
  assert.deepEqual(byClass(rows[0], "review-shot").map(
    (shot) => Number(shot.getAttribute("data-artifact-id"))), [40]);
  assert.equal(byClass(rows[1], "run-qa-check-mark")[0].textContent, "✕");
  assert.equal(byClass(rows[1], "run-qa-check-outcome")[0].textContent, "Failed");
  assert.equal(byClass(rows[2], "run-qa-check-run")[0].textContent, "Before merge");
  assert.equal(byClass(rows[2], "run-check-conclusion")[0].href, CI_URL);
});

test("no line repeats a phase code, the card's own run ID, or a release label", () => {
  const text = paint().textContent;
  assert.doesNotMatch(text, /post-deploy|verification|this release|deployed revision/);
  assert.doesNotMatch(text, new RegExp(RUN_ID));
});

test("with nothing run against the deployed revision, all checks are earlier checks", () => {
  const section = paint(history.slice(0, 3));
  assert.equal(checkLines(section).length, 0);
  assert.equal(checkLines(byClass(section, "run-qa-history")[0]).length, 3);
});

test("a carried title the run payload omits is read from the item", async () => {
  const documentNode = new FakeDocument();
  const reads = [];
  const context = { document: documentNode, client: { async call(request) {
    reads.push(request);
    return { status: 200, envelope: { success: true,
      result: { item: { title: `Title of ${request.target.public_ref}` } } } };
  } } };
  const items = [
    { id: 3416, ref: "YOK-3416", title: "", project_id: 1, project_sequence: 3416 },
    { id: 3418, ref: "YOK-3418", title: "Already named", project_id: 1, project_sequence: 3418 },
  ];
  const titles = await loadMissingItemTitles(context, items);
  assert.deepEqual(reads.map((request) => [request.function, request.target.public_ref]),
    [["items.detail.get", "YOK-3416"]]);
  const host = documentNode.createElement("div");
  appendCarriedItemHeading(documentNode, host, items[0], 1, titles);
  const title = byClass(host, "carried-item-title")[0];
  assert.equal(title.textContent, "Title of YOK-3416");
  assert.equal(title.href, "#/items/3416?project=1");
});

test("a repaint reuses a ready artifact read and retries a failed one", async () => {
  let calls = 0;
  let ready = true;
  const context = { client: { async call() {
    calls += 1;
    return ready
      ? { status: 200, envelope: { success: true, result: { disposition: "ready",
        content_type: "image/png", content_base64: "aVZCT1J3MEs=" } } }
      : { status: 500, envelope: { success: false, error: { message: "down" } } };
  } } };
  await readArtifact(context, { id: 1, requirement_id: 9 });
  await readArtifact(context, { id: 1, requirement_id: 9 });
  assert.equal(calls, 1);
  ready = false;
  await readArtifact(context, { id: 2, requirement_id: 9 });
  await new Promise((resolve) => setTimeout(resolve, 0));
  await readArtifact(context, { id: 2, requirement_id: 9 });
  assert.equal(calls, 3);
});
