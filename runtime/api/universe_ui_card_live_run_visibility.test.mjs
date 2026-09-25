// Live delivery boxes: an in-flight run with no members, and two live
// runs to different environments, both have to appear on the card.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

const HOUR = 60 * 60 * 1000;
const ago = (hours) => new Date(Date.now() - hours * HOUR).toISOString();
const FLOW = "yoke-hosted-production";
const ITEM_ID = 450;

function itemRow() {
  return {
    internal_id: ITEM_ID,
    title: "carry this somewhere",
    public_ref: "YOK-50",
    status: "release",
    project: "yoke",
    project_id: 1,
    project_sequence: 50,
    workflow_id: "issue",
    deployment_flow: FLOW,
    created_at: ago(6),
    updated_at: ago(1),
  };
}

function run(id, facts = {}) {
  return {
    id,
    project: "yoke",
    flow: FLOW,
    target_environment: "prod",
    status: "executing",
    created_at: ago(0.25),
    completed_at: "",
    stages: [{ name: "item-qa", state: "active" }],
    member_items: [],
    contained_items: [],
    ...facts,
  };
}

async function mount(runs) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  const client = workbenchClient({
    "items.overview.list": { rows: [itemRow()] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": { rows: runs },
  });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  const cards = byClass(byClass(root, "work-band-release")[0], "work-item-card");
  return {
    mounted,
    restore: () => { globalThis.fetch = originalFetch; },
    box: byClass(cards[0], "item-delivery")[0],
  };
}

test("an in-flight run with no members still draws from contained_items", async () => {
  const { mounted, restore, box } = await mount([
    run("run-stage", {
      flow: "yoke-hosted-stage-consumer-bound",
      target_environment: "stage",
      contained_items: [{ id: ITEM_ID }],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-stage");
    assert.match(
      byClass(box, "item-deployment-time")[0].textContent,
      /^Deploying since .+ ago$/,
    );
    assert.equal(
      byClass(box, "item-deployment-environment")[0].textContent, "stage",
    );
    assert.equal(byClass(box, "item-delivery-empty").length, 0);
  } finally {
    mounted.unmount();
    restore();
  }
});

test("concurrent live runs to different environments both show", async () => {
  const { mounted, restore, box } = await mount([
    run("run-prod", {
      created_at: ago(1),
      member_items: [{ id: ITEM_ID, ref: "YOK-50" }],
    }),
    run("run-stage", {
      flow: "yoke-hosted-stage-consumer-bound",
      target_environment: "stage",
      created_at: ago(2),
      contained_items: [{ id: ITEM_ID }],
    }),
  ]);
  try {
    assert.deepEqual(
      byClass(box, "item-deployment-run").map((node) => node.textContent),
      ["run-prod", "run-stage"],
    );
  } finally {
    mounted.unmount();
    restore();
  }
});

test("terminal runs ignore a stale containment snapshot", async () => {
  const { mounted, restore, box } = await mount([
    run("run-stage", {
      status: "failed",
      contained_items: [{ id: ITEM_ID }],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run").length, 0);
  } finally {
    mounted.unmount();
    restore();
  }
});

test("a mixed project run keeps candidate delivery beside real membership", async () => {
  const { mounted, restore, box } = await mount([
    run("run-mixed", {
      project_id: 2,
      member_items: [{ id: 999, project_id: 2, ref: "PLAT-9" }],
      delivery_candidate_items: [{ id: ITEM_ID, project_id: 1 }],
    }),
  ]);
  try {
    assert.deepEqual(
      byClass(box, "item-deployment-run").map((node) => node.textContent),
      ["run-mixed"],
    );
    assert.equal(
      byClass(box, "item-deployment-relation")[0].textContent,
      "candidate contains landing",
    );
    assert.equal(
      byClass(box, "item-deployment")[0].href,
      "#/deployments/runs/run-mixed?project=2",
    );
  } finally {
    mounted.unmount();
    restore();
  }
});

test("a later containing candidate does not revive delivered work", async () => {
  const { mounted, restore, box } = await mount([
    run("run-stage-later", {
      target_environment: "stage",
      contained_items: [{ id: ITEM_ID }],
      delivery_candidate_items: [],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment").length, 0);
    assert.equal(byClass(box, "item-delivery-empty").length, 1);
  } finally {
    mounted.unmount();
    restore();
  }
});

test("a run member remains visible when candidate delivery is settled", async () => {
  const { mounted, restore, box } = await mount([
    run("run-member", {
      member_items: [{ id: ITEM_ID, project_id: 1 }],
      delivery_candidate_items: [],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-member");
    assert.equal(byClass(box, "item-deployment-relation")[0].textContent, "run member");
  } finally {
    mounted.unmount();
    restore();
  }
});
