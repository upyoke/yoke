import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";
import {
  appendItemDelivery, deploymentsByItemId,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_deployment.js";

const item = { public_ref: "SAMPLE-51", project_id: 7 };
const run = (id, facts = {}) => ({
  id, project_id: 7, target_environment: "prod", status: "executing",
  created_at: "2026-10-01T12:00:00Z", member_items: [item], ...facts,
});
function card(runs) {
  const document = new FakeDocument();
  return appendItemDelivery(document, document.createElement("div"), item,
    deploymentsByItemId(runs));
}

test("a recorded removal supersedes old membership and candidate containment", () => {
  const removed = run("run-removed", {
    created_at: "2026-10-02T12:00:00Z", member_items: [],
    delivery_candidate_items: [item],
    removed_member_items: [{ ...item, reason: "QA awaits a repaired golden" }],
  });
  const index = deploymentsByItemId([run("run-old", { status: "failed" }), removed]);
  assert.equal(index.get("SAMPLE-51").filter((r) => r.id === removed.id).length, 1);
  const box = card([run("run-old", { status: "failed" }), removed]);
  const outcome = byClass(box, "item-deployment-outcome")[0];
  assert.equal(outcome.textContent, "○ removed · QA cancelled · rides a later release");
  assert.equal(outcome.title, "QA awaits a repaired golden");
  assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-removed");
  assert.equal(byClass(box, "item-deployment-relation")[0].textContent, "removed");
  assert.doesNotMatch(box.textContent, /not yet|QA unavailable|run-old/);
});

test("a removal names and links its recorded later holder", () => {
  const box = card([run("run-removed", {
    removed_member_items: [{ ...item, later_run_id: "run-later" }],
  })]);
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent,
    "○ removed · QA cancelled · rides run-later");
  assert.equal(byClass(box, "overview-card-link")[0].href,
    "/deployments/runs/run-later?project=7");
});

test("a newer real membership replaces the removal row", () => {
  const box = card([
    run("run-removed", { member_items: [], removed_member_items: [item] }),
    run("run-later", { created_at: "2026-10-02T12:00:00Z", status: "succeeded" }),
  ]);
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "○ awaiting item completion");
  assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-later");
});

test("failed and cancelled deployments remain readable when member QA is unreadable", () => {
  for (const status of ["failed", "cancelled", "executing", "succeeded"]) {
    const box = card([run("run-unreadable", {
      status, current_stage: "hosted-release",
      member_items: [{ ...item, item_qa: { state: "unreadable", reason: "Missing admitted subject" } }],
    })]);
    const outcome = byClass(box, "item-deployment-outcome")[0];
    assert.equal(outcome.textContent, ["failed", "cancelled"].includes(status)
      ? `✗ deployment ${status} · at hosted-release` : "○ QA unavailable");
    assert.equal(outcome.title, "Missing admitted subject");
  }
});

test("actual QA failure and accepted member evidence keep their presentation", () => {
  for (const [qa, expected] of [
    [{ state: "rejected" }, "✗ QA failed"],
    [{ state: "accepted" }, "◐ QA passed · awaiting item completion"],
    [{ state: "discharged" }, "◐ QA discharged · awaiting item completion"],
    [{ failed_requirement_ids: [9] }, "✗ QA failed · #9"],
  ]) {
    const box = card([run("run-qa", { member_items: [{ ...item, item_qa: qa }] })]);
    assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, expected);
  }
});
