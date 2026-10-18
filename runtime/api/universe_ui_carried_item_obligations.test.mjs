import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

test("the QA diagnostic spans the carried-item row", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /\.carried-item-qa-diagnostic\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
  assert.match(css, /\.carried-item-qa-diagnostic\s*\{[^}]*overflow-wrap:\s*anywhere/);
});

test("member QA rows name case and host, and the badge counts queued copies", () => {
  const queued = { ...pending, pending_obligation: false, requirement_id: 21,
    case_key: "release-home", host_baseline: "fresh-host", method_name: "Terminal check",
    instructions: "Open the shipping page.", outcome: "queued" };
  const waiting = { ...pending, requirement_id: 22, case_key: "release-home",
    host_baseline: "browser-approved", method_name: "Terminal check",
    instructions: "Sign in first." };
  const host = paint({ current: [queued, waiting], history: [] });
  assert.deepEqual(byClass(host, "run-qa-check-name").map((node) => node.textContent), [
    "Terminal check · release-home · fresh-host",
    "Terminal check · release-home · browser-approved",
  ]);
  assert.match(host.textContent, /Open the shipping page/);
  assert.match(host.textContent, /Sign in first/);
  assert.match(host.textContent, /0 of 2 passed · 1 pending · 1 queued/);
});
