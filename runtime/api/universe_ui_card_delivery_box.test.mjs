// The delivery box names one flow and one item outcome per environment.
//
// Release and Done draw it through one component, so every shape below is
// asserted on both bands from the same expectation: a box that told a
// waiting reader less than a finished one is the regression this covers.

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

// One item per band, identical in everything the delivery box reads, so a
// difference in what the two boxes say can only come from the renderer.
const BANDS = [
  {
    key: "release",
    itemId: 450,
    item: { public_ref: "YOK-50", status: "release", updated_at: ago(1) },
  },
  {
    key: "done",
    itemId: 460,
    item: {
      public_ref: "YOK-60",
      status: "done",
      terminal: true,
      finished: true,
      finished_at: ago(1),
    },
  },
];

function bandItem({ itemId, item }, facts = {}) {
  return {
    internal_id: itemId,
    title: "carry this somewhere",
    project: "yoke",
    project_id: 1,
    project_sequence: itemId - 400,
    workflow_id: "issue",
    deployment_flow: FLOW,
    created_at: ago(6),
    updated_at: ago(1),
    ...item,
    ...facts,
  };
}

function run(id, itemId, facts = {}) {
  return {
    id,
    project: "yoke",
    flow: FLOW,
    target_environment: "prod",
    status: "succeeded",
    created_at: ago(3),
    completed_at: ago(2),
    stages: [],
    member_items: [{ id: itemId, ref: "YOK-50", title: "carry this somewhere" }],
    ...facts,
  };
}

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

/**
 * Mount the Frontier with one card in `band`, and return that card's box.
 *
 * `runs` is built per band from its own item id, so the same run shapes
 * describe the same delivery whichever band is carrying them.
 */
async function mountBand(band, runsFor = () => [], facts = {}) {
  const client = workbenchClient({
    "items.overview.list": { rows: [bandItem(band, facts)] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": { rows: runsFor(band.itemId) },
  });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  const cards = byClass(byClass(root, `work-band-${band.key}`)[0], "work-item-card");
  return { mounted, root, box: byClass(cards[0], "item-delivery")[0] };
}


for (const band of BANDS) {
  test(`${band.key}: one flow header and one linked outcome per environment`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [
      run("run-prod", itemId),
      run("run-stage", itemId, {
        target_environment: "stage", member_items: [],
        carried_work: { items: [{ item_id: itemId }] },
      }),
    ], { delivery: { merges: 3, deployed: 1, not_deployed: 2 } });
    t.after(() => mounted.unmount());

    assert.equal(byClass(box, "item-delivery-flow")[0].textContent, FLOW);
    assert.equal(byClass(box, "item-delivery-merges").length, 0);
    assert.deepEqual(byClass(box, "item-deployment-environment").map((node) => node.textContent), ["prod", "stage"]);
    assert.deepEqual(byClass(box, "item-deployment-outcome").map((node) => node.textContent), ["✓ deployed", "✓ in build"]);
    assert.deepEqual(byClass(box, "item-deployment-relation").map((node) => node.textContent), ["member", "carried"]);
    assert.equal(byClass(box, "item-deployment-run")[0].href, "#/deployments/runs/run-prod?project=1");
    assert.equal(byClass(box, "state-pill").length, 0);
    assert.equal(byClass(box, "item-deployment-flow").length, 0);
    assert.equal(byClass(box, "item-deployment-wait").length, 0);
  });

  test(`${band.key}: the selected environment awaits its next release`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, () => [], {
      completion_environment: "prod",
    });
    t.after(() => mounted.unmount());
    assert.equal(byClass(box, "item-deployment-environment")[0].textContent, "prod");
    assert.equal(byClass(box, "item-deployment-outcome")[0].textContent, "○ not yet · next release");
    assert.equal(byClass(box, "item-deployment-placeholder")[0].textContent, "—");
    assert.equal(byClass(box, "item-deployment-run").length, 0);
  });

  test(`${band.key}: a stage run does not hide the production wait`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [
      run("run-stage", itemId, { target_environment: "stage" }),
    ], { completion_environment: "prod" });
    t.after(() => mounted.unmount());
    assert.deepEqual(byClass(box, "item-deployment-environment").map((node) => node.textContent), ["stage", "prod"]);
    assert.equal(byClass(box, "item-deployment-outcome")[1].textContent, "○ not yet · next release");
  });

  test(`${band.key}: only the newest attempt in each environment is shown`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [
      run("run-live", itemId, {
        status: "executing", current_stage: "item-qa",
        created_at: ago(1), completed_at: "",
      }),
      run("run-prod-old", itemId, { created_at: ago(2) }),
      run("run-stage", itemId, { target_environment: "stage", created_at: ago(4) }),
    ]);
    t.after(() => mounted.unmount());
    assert.deepEqual(byClass(box, "item-deployment-run").map((node) => node.textContent), ["run-live", "run-stage"]);
    assert.match(byClass(box, "item-deployment-outcome")[0].textContent, /^◐ deploying · at item-qa · 1h$/);
  });
}

test("the header resolves the item's single flow without repeating its source", async (t) => {
  stubFetch(t);
  for (const [facts, expected] of [
    [{ completion_flow: FLOW, completion_flow_source: "item" }, FLOW],
    [{ deployment_flow: "", completion_flow: FLOW, completion_flow_source: "project_default" }, FLOW],
    [{ deployment_flow: "", completion_flow: "", completion_flow_source: "none" }, "no flow"],
    [{ deployment_flow: "", delivery: { flow: FLOW } }, FLOW],
    [{ completion_flow_source: "unreadable" }, "its project default could not be read"],
  ]) {
    const { mounted, box } = await mountBand(BANDS[0], () => [], facts);
    assert.equal(byClass(box, "item-delivery-flow")[0].textContent, expected);
    mounted.unmount();
  }
});
