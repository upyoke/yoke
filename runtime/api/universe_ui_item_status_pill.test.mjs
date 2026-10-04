import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  claimingSession, descendantText, workbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

async function waitingCard(t, overrides) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient(overrides) });
  t.after(() => mounted.unmount());
  await settle();
  const waiting = byClass(root, "work-band-waiting")[0];
  return byClass(waiting, "work-item-card").find((card) => (
    byClass(card, "work-item-card-ref")[0].textContent === claimingSession().current_item
  ));
}

test("an unavailable owner's pill names the owner condition and retains its reason", async (t) => {
  const card = await waitingCard(t, {
    "sessions.list": { rows: [{
      ...claimingSession(), native_process: { state: "gone" },
    }] },
  });
  const pill = byClass(card, "item-status-pill")[0];
  assert.equal(descendantText(pill), "Owner unavailable");
  assert.ok(pill.classList.contains("is-owner-unavailable"));
  const detail = byClass(card, "item-status-detail")[0];
  assert.equal(byClass(detail, "item-status-detail-label")[0].textContent, "Owner unavailable");
  assert.equal(byClass(detail, "item-status-detail-copy")[0].textContent,
    "Held by a work claim whose session is no longer answering. "
      + "Release the claim or terminate the session to free this item.");
});

for (const named of [true, false]) {
  test(`a dependency pill ${named ? "names its blocker" : "names an unnamed dependency"}`, async (t) => {
    const itemRef = claimingSession().current_item;
    const blockerRef = `${itemRef.split("-")[0]}-${Number(itemRef.split("-")[1]) + 1}`;
    const card = await waitingCard(t, {
      "frontier.list": {
        ready_rows: [],
        blocked_rows: [{
          item_id: itemRef,
          project_id: 1,
          project: "yoke",
          why: "An upstream fact is unsatisfied.",
          ...(named ? { blocking_item: blockerRef } : {}),
        }],
      },
    });
    const pill = byClass(card, "item-status-pill")[0];
    assert.equal(descendantText(pill), named ? `Waiting for ${blockerRef}` : "Waiting on dependency");
    assert.ok(pill.classList.contains("is-dependency"));
  });
}
