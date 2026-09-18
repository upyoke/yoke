// The delivery box a Release-band card carries: which flow ships it, and
// which runs have picked it up. Drawn even when none have, because "merged,
// in no run yet" is the state the band exists to show.

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

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountAt(hash, client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

// The Release band's delivery box is drawn for every card it holds, because
// "merged, in no run yet" is a state the band exists to show — unlike Done,
// where a box with no run would describe nothing.
function releasingItem(facts = {}) {
  const hour = 60 * 60 * 1000;
  return {
    public_ref: "YOK-50",
    internal_id: 450,
    title: "waiting to ship",
    project: "yoke",
    project_id: 1,
    project_sequence: 50,
    workflow_id: "issue",
    status: "release",
    deployment_flow: "yoke-hosted-production",
    created_at: new Date(Date.now() - 6 * hour).toISOString(),
    updated_at: new Date(Date.now() - hour).toISOString(),
    ...facts,
  };
}

function run(id, facts = {}) {
  const hour = 60 * 60 * 1000;
  return {
    id,
    project: "yoke",
    flow: "yoke-hosted-production",
    target_environment: "prod",
    status: "succeeded",
    created_at: new Date(Date.now() - 3 * hour).toISOString(),
    completed_at: new Date(Date.now() - 2 * hour).toISOString(),
    stages: [],
    member_items: [{ id: 450, ref: "YOK-50", title: "waiting to ship" }],
    ...facts,
  };
}

async function mountRelease(t, runs) {
  const client = workbenchClient({
    "items.overview.list": { rows: [releasingItem()] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": { rows: runs },
  });
  const { mounted, root } = await mountAt("#/frontier?project=1", client);
  return { mounted, box: byClass(root, "release-delivery")[0] };
}

test("a Release card in no run says so, with no empty sub-card", async (t) => {
  stubFetch(t);
  const { mounted, box } = await mountRelease(t, []);

  assert.ok(box, "the box is drawn even with no run");
  assert.equal(byClass(box, "release-delivery-flow")[0].textContent, "yoke-hosted-production");
  assert.equal(byClass(box, "release-delivery-empty")[0].textContent, "Not in a run yet");
  assert.equal(byClass(box, "release-delivery-run").length, 0);
  mounted.unmount();
});

test("a Release card in one run draws that run, and omits its own flow", async (t) => {
  stubFetch(t);
  const { mounted, box } = await mountRelease(t, [run("run-1")]);

  const cards = byClass(box, "release-delivery-run");
  assert.equal(cards.length, 1);
  assert.equal(byClass(cards[0], "release-delivery-run-id")[0].textContent, "run-1");
  assert.equal(
    byClass(cards[0], "release-delivery-run-environment")[0].textContent, "prod",
  );
  // Same flow as the item's own, so repeating it would say nothing.
  assert.equal(byClass(cards[0], "release-delivery-run-flow").length, 0);
  assert.equal(byClass(box, "release-delivery-empty").length, 0);
  mounted.unmount();
});

test("several runs cap at the live one plus the newest success per environment", async (t) => {
  stubFetch(t);
  const hour = 60 * 60 * 1000;
  const { mounted, box } = await mountRelease(t, [
    run("run-live", {
      status: "executing",
      created_at: new Date(Date.now() - 1 * hour).toISOString(),
      completed_at: "",
    }),
    run("run-prod-new", { created_at: new Date(Date.now() - 2 * hour).toISOString() }),
    // Superseded by the newer success to the same environment.
    run("run-prod-old", { created_at: new Date(Date.now() - 9 * hour).toISOString() }),
    // A different environment keeps its own newest success.
    run("run-stage", {
      target_environment: "stage",
      created_at: new Date(Date.now() - 4 * hour).toISOString(),
    }),
    // A failure a later success replaced is history, not a sub-card.
    run("run-failed", {
      status: "failed",
      created_at: new Date(Date.now() - 5 * hour).toISOString(),
    }),
    // Another flow's run still counts as carrying, and names that flow.
    run("run-other-flow", {
      flow: "yoke-hosted-ancillary",
      target_environment: "sandbox",
      created_at: new Date(Date.now() - 6 * hour).toISOString(),
    }),
  ]);

  assert.deepEqual(
    byClass(box, "release-delivery-run-id").map((node) => node.textContent),
    ["run-live", "run-prod-new", "run-stage", "run-other-flow"],
  );
  assert.deepEqual(
    byClass(box, "release-delivery-run-flow").map((node) => node.textContent),
    ["yoke-hosted-ancillary"],
  );
  mounted.unmount();
});
