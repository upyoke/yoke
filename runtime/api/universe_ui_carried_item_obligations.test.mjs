import assert from "node:assert/strict";
import test from "node:test";
import { byClass, FakeDocument } from "./universe_ui_dom_test_support.mjs";
import { appendCarriedItemEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { member, readingContext, readingClient, RUN_ID } from "./universe_ui_carried_item_test_support.mjs";

function paint(projection, rows = []) {
  const document = new FakeDocument();
  const host = document.createElement("div");
  appendCarriedItemEvidence(readingContext(document, readingClient()), host, {
    item: member(1, ["SAMPLE", 1].join("-"), { qa_obligations: projection }), runId: RUN_ID,
    facts: { byItem: new Map([["SAMPLE-1", rows]]) },
  });
  return host;
}
const pending = { project: 1, requirement_id: 10, pending_obligation: true, run_id: null,
  deployment_run_id: RUN_ID, method_name: "Browser inspection", qa_phase: "post_deploy",
  outcome: "queued", artifacts: [] };

test("source-only QA appears as not started, with no borrowed result or evidence", () => {
  const host = paint({ current: [pending], history: [] }, [
    { ...pending, pending_obligation: false, deployment_run_id: "old-run", outcome: "passed" },
  ]);
  assert.match(host.textContent, /Item QA.*Not started.*Browser inspection.*Not started/);
  assert.equal(byClass(host, "run-qa-check").length, 1);
  assert.equal(byClass(host, "run-qa-check-name")[0].children[0].href, "/qa-activity/10?project=1");
  assert.equal(byClass(host, "review-shot").length, 0);
});

test("a deployment copy is displayed once and carries this run's verdict", () => {
  const copy = { ...pending, pending_obligation: false, requirement_id: 20, outcome: "passed" };
  const host = paint({ current: [copy], history: [] }, [copy]);
  assert.equal(byClass(host, "run-qa-check").length, 1);
  assert.match(host.textContent, /1 of 1 passed/);
});

test("waivers are explicit and never count as passing", () => {
  const host = paint({ current: [{ ...pending, waived_at: "2026-10-15T00:00:00Z" }], history: [] });
  assert.match(host.textContent, /Waived/);
  assert.doesNotMatch(host.textContent, /1 of 1 passed/);
});

test("an empty projection and a failed read are distinguishable", () => {
  assert.match(paint({ current: [], history: [] }).textContent, /No applicable item QA obligations/);
  const failed = paint({ current: [], history: [], error: "item_qa_requirements_read_failed: Reload this run." });
  assert.match(failed.textContent, /item_qa_requirements_read_failed.*Reload/);
  assert.doesNotMatch(failed.textContent, /No applicable/);
  assert.equal(byClass(failed, "carried-item-evidence").length, 0);
  assert.equal(byClass(failed, "run-qa-section").length, 0);
  assert.equal(byClass(failed, "carried-item-qa-diagnostic").length, 1);
});
