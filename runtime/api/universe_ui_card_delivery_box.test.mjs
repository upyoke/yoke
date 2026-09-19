// The delivery box a Frontier card carries: which flow ships this item, how
// much of it has landed, and which runs have picked it up.
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
import { descendantText, workbenchClient } from "./universe_ui_workbench_test_support.mjs";

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
  test(`${band.key}: the box names the flow and what has landed`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(
      band,
      (itemId) => [run("run-1", itemId)],
      { delivery: { merges: 3, deployed: 1, not_deployed: 2 } },
    );

    assert.ok(box, "the band draws a delivery box");
    assert.equal(byClass(box, "item-delivery-flow")[0].textContent, FLOW);
    assert.equal(
      byClass(box, "item-delivery-merges")[0].textContent,
      "3 merges · 1 deployed · 2 not deployed",
    );
    mounted.unmount();
  });

  test(`${band.key}: a run is a sub-card with its truck, state and time`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [run("run-1", itemId)]);

    const cards = byClass(box, "item-deployment");
    assert.equal(cards.length, 1);
    assert.equal(cards[0].href, "#/deployments/runs/run-1?project=1");
    assert.equal(byClass(cards[0], "item-deployment-icon").length, 1);
    assert.match(descendantText(cards[0]), /succeeded/);
    assert.equal(
      byClass(cards[0], "item-deployment-environment")[0].textContent, "prod",
    );
    assert.match(
      byClass(cards[0], "item-deployment-time")[0].textContent, /^Deployed .+ ago$/,
    );
    assert.equal(byClass(cards[0], "item-deployment-run")[0].textContent, "run-1");
    // Same flow as the item's own, so repeating it would say nothing.
    assert.equal(byClass(cards[0], "item-deployment-flow").length, 0);
    assert.equal(byClass(box, "item-delivery-empty").length, 0);
    mounted.unmount();
  });

  test(`${band.key}: no run yet is a muted truck saying so`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band);

    assert.ok(box, "the box is drawn even with no run");
    const empty = byClass(box, "item-delivery-empty")[0];
    assert.equal(descendantText(empty), "Not in a run yet");
    assert.equal(byClass(empty, "is-muted").length, 1, "the truck is greyed");
    // An empty sub-card would draw a box around a run that does not exist.
    assert.equal(byClass(box, "item-deployment").length, 0);
    mounted.unmount();
  });

  test(`${band.key}: several runs cap at the live one plus the newest success per environment`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [
      run("run-live", itemId, {
        status: "executing", created_at: ago(1), completed_at: "",
      }),
      run("run-prod-new", itemId, { created_at: ago(2) }),
      // Superseded by the newer success to the same environment.
      run("run-prod-old", itemId, { created_at: ago(9) }),
      // A different environment keeps its own newest success.
      run("run-stage", itemId, { target_environment: "stage", created_at: ago(4) }),
      // A failure a later success replaced is history, not a sub-card.
      run("run-failed", itemId, { status: "failed", created_at: ago(5) }),
      // Another flow's run still counts as carrying, and names that flow.
      run("run-other-flow", itemId, {
        flow: "yoke-hosted-ancillary",
        target_environment: "sandbox",
        created_at: ago(6),
      }),
    ]);

    assert.deepEqual(
      byClass(box, "item-deployment-run").map((node) => node.textContent),
      ["run-live", "run-prod-new", "run-stage", "run-other-flow"],
    );
    assert.deepEqual(
      byClass(box, "item-deployment-flow").map((node) => node.textContent),
      ["yoke-hosted-ancillary"],
    );
    mounted.unmount();
  });

  test(`${band.key}: a run still moving is present tense, not "Deployed"`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, (itemId) => [
      run("run-live", itemId, {
        status: "executing", created_at: ago(1), completed_at: "",
      }),
    ]);

    const when = byClass(box, "item-deployment-time")[0];
    assert.match(when.textContent, /^Deploying since .+ ago$/);
    assert.ok(when.getAttribute("datetime"));
    mounted.unmount();
  });

  test(`${band.key}: one landed merge is "1 merge"`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, () => [], {
      delivery: { merges: 1, deployed: 1, not_deployed: 0 },
    });

    assert.equal(
      byClass(box, "item-delivery-merges")[0].textContent,
      "1 merge · 1 deployed · 0 not deployed",
    );
    mounted.unmount();
  });

  test(`${band.key}: an item that has landed nothing says so rather than showing zeroes`, async (t) => {
    stubFetch(t);
    const { mounted, box } = await mountBand(band, () => [], {
      delivery: { merges: 0, deployed: 0, not_deployed: 0 },
    });

    assert.equal(byClass(box, "item-delivery-merges")[0].textContent, "no merges");
    mounted.unmount();
  });

  test(`${band.key}: a projection that carried no delivery block still draws the line`, async (t) => {
    stubFetch(t);
    // An older serving build answers without the field; the card must not
    // render "undefined merges" at a reader while that rolls out.
    const { mounted, box } = await mountBand(band);

    assert.equal(byClass(box, "item-delivery-merges")[0].textContent, "no merges");
    mounted.unmount();
  });

  test(`${band.key}: the flat-line rendering is gone`, async (t) => {
    stubFetch(t);
    const { mounted, root } = await mountBand(band, (itemId) => [run("run-1", itemId)]);

    for (const gone of [
      "release-delivery",
      "release-delivery-flow",
      "release-delivery-merges",
      "release-delivery-empty",
      "release-delivery-run",
      "release-delivery-run-id",
      "release-delivery-run-environment",
      "release-delivery-run-flow",
    ]) assert.equal(byClass(root, gone).length, 0, gone);
    mounted.unmount();
  });
}
