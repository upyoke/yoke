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
    title: "carry this somewhere",
    public_ref: "YOK-50",
    frontier_group: { section: "release", reason: "awaiting_delivery" }, status: "release",
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

async function mount(runs, item = itemRow(), band = "release") {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  const client = workbenchClient({
    "items.overview.list": { rows: [item] },
    "frontier.list": { ready_rows: [], blocked_rows: [], dependency_edges: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": { rows: runs },
  });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  const cards = byClass(byClass(root, `work-band-${band}`)[0], "work-item-card");
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
      contained_items: [{ public_ref: "YOK-50" }],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-stage");
    assert.match(
      byClass(box, "item-deployment-outcome")[0].textContent,
      /^◐ deploying · at item-qa · \d+[mhd]$/,
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
      member_items: [{ public_ref: "YOK-50" }],
    }),
    run("run-stage", {
      flow: "yoke-hosted-stage-consumer-bound",
      target_environment: "stage",
      created_at: ago(2),
      contained_items: [{ public_ref: "YOK-50" }],
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
      contained_items: [{ public_ref: "YOK-50" }],
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
      delivery_candidate_items: [{ public_ref: "YOK-50", project_id: 1 }],
    }),
  ]);
  try {
    assert.deepEqual(
      byClass(box, "item-deployment-run").map((node) => node.textContent),
      ["run-mixed"],
    );
    assert.equal(
      byClass(box, "item-deployment-relation")[0].textContent,
      "carried",
    );
    assert.equal(
      byClass(box, "item-deployment-run")[0].href,
      "/deployments/runs/run-mixed?project=2",
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
      contained_items: [{ public_ref: "YOK-50" }],
      delivery_candidate_items: [],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run").length, 0);
    assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "○ Merged · not deployed yet · next release");
  } finally {
    mounted.unmount();
    restore();
  }
});

test("a run member remains visible when candidate delivery is settled", async () => {
  const { mounted, restore, box } = await mount([
    run("run-member", {
      member_items: [{ public_ref: "YOK-50", project_id: 1 }],
      delivery_candidate_items: [],
    }),
  ]);
  try {
    assert.equal(byClass(box, "item-deployment-run")[0].textContent, "run-member");
    assert.equal(byClass(box, "item-deployment-relation")[0].textContent, "member");
  } finally {
    mounted.unmount();
    restore();
  }
});


// Rows are keyed by environment: their order follows creation time, which
// is incidental here, so both fixture orders must give the same outcomes.
function outcomesByEnvironment(box) {
  return Object.fromEntries(byClass(box, "item-deployment").map((row) => [
    byClass(row, "item-deployment-environment")[0].textContent,
    byClass(row, "item-deployment-outcome")[0].textContent,
  ]));
}

for (const order of ["stable", "reversed"]) {
  test(`a promoted carried build has its own outcome while item QA stays open (${order} order)`, async () => {
    const carried = run("run-stage", {
      target_environment: "stage",
      build_promoted: true,
      delivery_candidate_items: [{ public_ref: "YOK-50" }],
      member_items: [{ ref: "YOK-51", item_qa: { state: "pending" } }],
    });
    const active = run("run-prod", {
      build_promoted: true,
      member_items: [{ ref: "YOK-50", item_qa: { state: "pending" } }],
    });
    const runs = order === "stable" ? [carried, active] : [active, carried];
    const { mounted, restore, box } = await mount(runs);
    try {
      const outcomes = outcomesByEnvironment(box);
      assert.deepEqual(Object.keys(outcomes).sort(), ["prod", "stage"]);
      assert.equal(outcomes.stage, "○ in build");
      assert.match(outcomes.prod, /^◐ deploying · at item-qa · \d+[mhd]$/);
    } finally {
      mounted.unmount();
      restore();
    }
  });
}

test("a done card keeps its first carried link outside the run roster", async () => {
  const item = {
    ...itemRow(),
    status: "done",
    finished: true,
    finished_at: ago(2),
    frontier_group: { section: "done", reason: "finished" },
    delivery: {
      carried_builds: [{ id: "run-stage-first", project_id: 2, target_environment: "stage" }],
      completed_deliveries: [{ run_id: "run-prod", run_project_id: 1, environment: "prod" }],
    },
  };
  const { mounted, restore, box } = await mount([
    run("run-stage-later", { target_environment: "stage", delivery_candidate_items: [] }),
  ], item, "done");
  try {
    const links = byClass(box, "item-deployment-run");
    assert.deepEqual(links.map((link) => link.textContent), ["run-stage-first", "run-prod"]);
    assert.equal(links[0].href, "/deployments/runs/run-stage-first?project=2");
    assert.deepEqual(byClass(box, "item-deployment-outcome").map((node) => node.textContent), [
      "○ in build", "✓ deployed · item completed",
    ]);
  } finally {
    mounted.unmount();
    restore();
  }
});
