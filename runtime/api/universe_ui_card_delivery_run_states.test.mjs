import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  shownDeliveryRuns, appendItemDelivery, deploymentsByItemId,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_deployment.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

const MINUTE = 60 * 1000;
const ago = (minutes) => new Date(Date.now() - minutes * MINUTE).toISOString();
const ITEM_ID = 450;
const ITEM_SEQUENCE = 50;
const ITEM_REF = `YOK-${ITEM_SEQUENCE}`;

function run(id, status, minutes, facts = {}) {
  return {
    id,
    status,
    target_environment: "prod",
    created_at: ago(minutes),
    completed_at: status === "succeeded" || status === "failed"
      ? ago(minutes - 1)
      : "",
    ...facts,
  };
}

test("the newest failed run remains visible over an older success", () => {
  const shown = shownDeliveryRuns([
    run("run-succeeded", "succeeded", 60),
    run("run-failed", "failed", 20),
  ]);

  assert.deepEqual(shown.map(({ id }) => id), ["run-failed"]);
});

test("a newer success supersedes the environment's older failure", () => {
  const shown = shownDeliveryRuns([
    run("run-failed", "failed", 60),
    run("run-succeeded", "succeeded", 20),
  ]);

  assert.deepEqual(shown.map(({ id }) => id), ["run-succeeded"]);
});

test("an older in-flight run shows its stage and elapsed time", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const client = workbenchClient({
    "items.overview.list": {
      rows: [{
        internal_id: ITEM_ID,
        public_ref: ITEM_REF,
        project: "yoke",
        project_id: 1,
        project_sequence: ITEM_SEQUENCE,
        title: "Show active runs",
        workflow_id: "dash",
        status: "release",
        completion_flow: "flow",
        completion_flow_source: "item",
        delivery: { merges: 1, deployed: 0, not_deployed: 1 },
        created_at: ago(90),
      }],
    },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": {
      rows: [{
        ...run("run-active", "executing", 45), current_stage: "item-qa",
        project: "yoke",
        flow: "flow",
        stages: [],
        member_items: [{ id: ITEM_ID, ref: ITEM_REF, title: "Show active runs" }],
      }],
    },
  });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  t.after(() => mounted.unmount());
  await settle();

  assert.match(
    byClass(root, "item-deployment-outcome")[0].textContent,
    /^◐ deploying · at item-qa · 45m$/,
  );
});

function deliveryBox(facts, others = []) {
  const documentNode = new FakeDocument();
  const card = documentNode.createElement("div");
  const active = {
    ...run("run-current", "executing", 120), current_stage: "item-qa",
    member_items: [{ id: ITEM_ID, ref: ITEM_REF, status: "release", ...facts }, ...others],
  };
  return appendItemDelivery(documentNode, card, {
    internal_id: ITEM_ID, project_id: 1, completion_flow: "flow",
  }, deploymentsByItemId([active]));
}

test("a member's passed QA is deployed even while its run waits on another member", () => {
  const siblingRef = `YOK-${ITEM_SEQUENCE + 1}`;
  const box = deliveryBox({ item_qa: { state: "accepted" } }, [
    { id: ITEM_ID + 1, ref: siblingRef, status: "release", item_qa: { state: "awaiting review" } },
  ]);
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "✓ deployed · QA passed");
  assert.equal(byClass(box, "item-deployment-wait")[0].textContent, `run still open: waiting on ${siblingRef}`);
  assert.equal(byClass(box, "item-deployment-wait").length, 1);
});

test("a failed member names its own QA requirement without blaming the whole run", () => {
  const requirementId = 81;
  const box = deliveryBox({ item_qa: { state: "cases unresolved", failed_requirement_ids: [requirementId] } });
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, `✗ QA failed · #${requirementId}`);
  assert.equal(byClass(box, "item-deployment-wait").length, 0);
});

test("unrun or unresolved QA remains deploying, rather than claiming failure", () => {
  for (const state of ["not yet run", "cases unresolved", "awaiting review"]) {
    const box = deliveryBox({ item_qa: { state, failed_requirement_ids: [] } });
    assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "◐ deploying · at item-qa · 2h");
    assert.equal(byClass(box, "item-deployment-wait").length, 0);
  }
});

test("a discharge remains distinct from a passing QA result", () => {
  const box = deliveryBox({ item_qa: { state: "discharged" } });
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "✓ deployed · QA discharged");
});

test("a sibling's rejected QA is a run wait even after its item finished", () => {
  const siblingRef = `YOK-${ITEM_SEQUENCE + 1}`;
  const box = deliveryBox({ item_qa: { state: "accepted" } }, [{
    id: ITEM_ID + 1, ref: siblingRef, status: "done", item_qa: { state: "rejected" },
  }]);
  assert.equal(byClass(box, "item-deployment-wait")[0].textContent,
    `run still open: waiting on ${siblingRef}`);
});

test("an unreadable member QA reports why rather than implying success", () => {
  const box = deliveryBox({ item_qa: { state: "unreadable", reason: "target missing; re-drive the release" } });
  const outcome = byClass(box, "item-deployment-outcome")[0];
  assert.equal(outcome.textContent, "○ QA unavailable");
  assert.match(outcome.title, /re-drive/);
});

test("a terminal member run has no remaining-wait sub-line", () => {
  const documentNode = new FakeDocument();
  const box = appendItemDelivery(documentNode, documentNode.createElement("div"), {
    internal_id: ITEM_ID,
  }, deploymentsByItemId([{
    ...run("run-finished", "succeeded", 20),
    member_items: [{ id: ITEM_ID, item_qa: { state: "accepted" } }],
  }]));
  assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "✓ deployed · QA passed");
  assert.equal(byClass(box, "item-deployment-wait").length, 0);
});
