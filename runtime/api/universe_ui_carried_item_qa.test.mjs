// A carried item's QA inside its run entry: the check that ran against the
// deployed revision leads with its screenshots, and every other check is one
// row behind a single "Earlier checks" disclosure, each linking its own QA
// case, run or CI run.

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
import { paintCarriedItemQa } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_qa.js";
import {
  appendCarriedItemHeading,
  loadMissingItemTitles,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_titles.js";

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
    happened_at: "2026-09-10T08:00:00Z" }),
  check({ requirement_id: 13, deployment_run_id: OLDER_RUN, qa_phase: "post_deploy",
    outcome: "failed", execution_target_json: deployedTarget("0ld"),
    happened_at: "2026-09-10T07:00:00Z" }),
  check({ requirement_id: 14, deployment_run_id: RUN_ID, qa_phase: "post_deploy",
    execution_target_json: deployedTarget(DEPLOYED_SHA),
    artifacts: [
      { id: 90, artifact_type: "command_output", content_type: "text/plain" },
      ...[1, 2, 3, 4, 5].map((id) => artifact(id, 14)),
    ],
    happened_at: "2026-09-10T10:00:00Z" }),
];

function paint(rows = history) {
  const documentNode = new FakeDocument();
  const wrap = documentNode.createElement("div");
  const context = { document: documentNode, projects: () => [{ id: 1, slug: "yoke" }],
    client: { call: async () => ({ status: 200, envelope: { success: true, result: {} } }) } };
  paintCarriedItemQa(context, wrap, rows, { runId: RUN_ID, deployedSha: DEPLOYED_SHA, project: 1 });
  return wrap;
}

test("QA for the deployed revision leads, then its screenshots, then earlier checks", () => {
  const wrap = paint();
  const classes = wrap.children.map((node) => node.className.split(" ")[0]);
  assert.deepEqual(classes, [
    "carried-item-qa-heading", "carried-item-qa-row", "review-evidence",
    "carried-item-qa-earlier",
  ]);
  assert.equal(wrap.children[0].textContent, "QA for the deployed revision");
  const current = wrap.children[1];
  assert.match(current.textContent, /^✓Command check passed·this release·.*·View output$/);
  assert.equal(current.children[1].href, "#/qa-activity/14?project=1");
  assert.equal(byClass(current, "carried-item-qa-output")[0].href, "#/qa-activity/14?project=1");
});

test("the deployed revision's screenshots open and close the rest in place", () => {
  const strip = paint().children[2];
  assert.equal(byClass(strip, "review-shot").length, 3);
  const more = byClass(strip, "review-more")[0];
  assert.equal(more.textContent, "and 2 more");
  more.dispatchEvent(new Event("click"));
  assert.equal(byClass(strip, "review-shot").length, 5);
});

test("every other check is one row behind one Earlier checks disclosure", () => {
  const earlier = byClass(paint(), "carried-item-qa-earlier")[0];
  assert.equal(earlier.tagName, "DETAILS");
  assert.equal(earlier.children[0].textContent, "Earlier checks");
  const rows = byClass(earlier, "carried-item-qa-row");
  assert.equal(rows.length, 3);
  // Newest first: an older release's pass, its failure, then before merge.
  assert.match(rows[0].textContent, /^✓Run 20260910-002·.*·older revision$/);
  const runLink = byClass(rows[0], "carried-item-qa-run")[0];
  assert.equal(runLink.href, `#/deployments/runs/${OLDER_RUN}?project=1`);
  assert.equal(rows[0].children.at(-1).href, "#/qa-activity/12?project=1");
  // A check that did not pass says how it ended.
  assert.match(rows[1].textContent, /^✕Run 20260910-002·.*·older revision·failed$/);
  assert.match(rows[2].textContent, /^✓Before merge·.*·GitHub Actions$/);
  assert.equal(rows[2].children[1].href, "#/qa-activity/11?project=1");
  assert.equal(byClass(rows[2], "carried-item-qa-ci")[0].href, CI_URL);
});

test("no row repeats a phase code, the card's own run ID, or a check count", () => {
  const text = paint().textContent;
  assert.doesNotMatch(text, /post-deploy|before merge ·|verification/);
  assert.doesNotMatch(text, new RegExp(RUN_ID));
  assert.doesNotMatch(text, /more checks|not the revision that is deployed/);
});

test("with nothing run against the deployed revision, all checks are earlier checks", () => {
  const wrap = paint(history.slice(0, 3));
  assert.equal(byClass(wrap, "carried-item-qa-heading").length, 0);
  assert.equal(byClass(byClass(wrap, "carried-item-qa-earlier")[0],
    "carried-item-qa-row").length, 3);
});

test("the strip holds every screenshot the item's checks captured, each once", () => {
  const rows = [
    ...history,
    check({ requirement_id: 15, deployment_run_id: OLDER_RUN, qa_phase: "post_deploy",
      artifacts: [artifact(3, 15), artifact(40, 15), artifact(41, 15)],
      happened_at: "2026-09-10T06:00:00Z" }),
  ];
  const strip = paint(rows).children[2];
  assert.equal(byClass(strip, "review-more")[0].textContent, "and 4 more");
  byClass(strip, "review-more")[0].dispatchEvent(new Event("click"));
  assert.deepEqual(byClass(strip, "review-shot").map(
    (shot) => Number(shot.getAttribute("data-artifact-id"))), [1, 2, 3, 4, 5, 40, 41]);
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
