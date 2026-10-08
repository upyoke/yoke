import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  claimingSession, descendantText, workbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

async function bandCard(t, bandKey, overrides) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient(overrides) });
  t.after(() => mounted.unmount());
  await settle();
  const band = byClass(root, `work-band-${bandKey}`)[0];
  return byClass(band, "work-item-card").find((card) => (
    byClass(card, "work-item-card-ref")[0].textContent === claimingSession().current_item
  ));
}

function blockedRow(blocker, why) {
  return {
    public_ref: claimingSession().current_item,
    project_id: 1,
    project: "yoke",
    why,
    ...(blocker ? { blocking_item: blocker } : {}),
  };
}

test("an unavailable owner's pill names the owner condition and retains its reason", async (t) => {
  const card = await bandCard(t, "hold", {
    "sessions.list": { rows: [{
      ...claimingSession(), liveness: "stale", native_process: { state: "gone" },
    }] },
  });
  const pill = byClass(card, "item-status-pill")[0];
  assert.equal(descendantText(pill), "Owner unavailable");
  assert.ok(pill.classList.contains("is-owner-unavailable"));
  const detail = byClass(card, "item-status-detail")[0];
  assert.equal(byClass(detail, "item-status-detail-label")[0].textContent, "Owner unavailable");
  assert.equal(byClass(detail, "item-status-detail-copy")[0].textContent,
    "Held by a work claim whose session is abandoned: not parked, its "
      + "process gone, and quiet past its activity window. Release the claim "
      + "or terminate the session to free this item.");
});

for (const [rows, label] of [
  [[blockedRow("YOK-10", "Waits on YOK-99.")], "Waiting for YOK-10"],
  [[blockedRow("YOK-10", "first"), blockedRow("YOK-11", "second")], "Waiting for 2 items"],
]) {
  test(`a dependency pill reads "${label}" from the blocked rows' own items`, async (t) => {
    // Claimed, so the card is drawn in Active with its reason still on it.
    const card = await bandCard(t, "active", {
      "frontier.list": { ready_rows: [], blocked_rows: rows, dependency_edges: [] },
      "sessions.list": { rows: [claimingSession()] },
    });
    const pill = byClass(card, "item-status-pill")[0];
    assert.equal(descendantText(pill), label);
    assert.ok(pill.classList.contains("is-dependency"));
    const copy = byClass(card, "item-status-detail-copy")[0].textContent;
    for (const row of rows) assert.match(copy, new RegExp(row.why.replace(".", "\\.")));
  });
}

test("a wait that names no blocking item is held, not a dependency", async (t) => {
  const card = await bandCard(t, "hold", {
    "frontier.list": {
      ready_rows: [],
      blocked_rows: [blockedRow(null, "Idea body is title-only.")],
      dependency_edges: [],
    },
  });
  const pill = byClass(card, "item-status-pill")[0];
  assert.equal(descendantText(pill), "Held");
  assert.ok(pill.classList.contains("is-blocked"));
});
