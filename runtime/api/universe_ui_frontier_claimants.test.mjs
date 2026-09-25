import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  claimingSession,
  descendantText,
  recentIso,
  workbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

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
  return { root, mounted };
}

const band = (root, key) => byClass(root, `work-band-${key}`)[0];

function cardFor(root, ref) {
  return byClass(root, "work-item-card").find(
    (card) => byClass(card, "work-item-card-ref")[0]?.textContent === ref,
  );
}

function item(sequence, title, fields = {}) {
  return {
    public_ref: `YOK-${sequence}`,
    internal_id: 100 + sequence,
    title,
    project: "yoke",
    project_id: 1,
    project_sequence: sequence,
    workflow_id: "dash",
    status: "implementing",
    created_at: recentIso(12),
    updated_at: recentIso(1),
    ...fields,
  };
}

function holder(sessionId, ref, title, fields = {}) {
  return {
    ...claimingSession(),
    session_id: sessionId,
    current_item: ref,
    current_item_title: title,
    claims: [{ target_kind: "item", public_ref: ref, target: ref }],
    holdings: { current: [], previous: [], previous_remainder: 0 },
    ...fields,
  };
}

// One claimed item per band a claim can sit in, plus one nobody holds. Band
// membership and who holds the item are separate facts, so each claimed card
// carries its holder whichever band drew it.
function claimedEverywhereClient() {
  return workbenchClient({
    "items.overview.list": { rows: [
      item(9, "Ship typed workflows"),
      item(11, "Land the release band", { status: "release", merged_at: recentIso(1) }),
      item(12, "Wait on the schema", { blocked: true, blocked_reason: "Needs the schema." }),
      item(13, "Hold the freeze", { frozen: true, blocked_reason: "Frozen for review." }),
    ] },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [
      holder("s-active", "YOK-9", "Ship typed workflows"),
      holder("s-release", "YOK-11", "Land the release band", { mode: "parked" }),
      holder("s-frozen", "YOK-13", "Hold the freeze"),
    ] },
  });
}

test("every claimed card carries its holder, whichever band drew it", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", claimedEverywhereClient());

  assert.ok(byClass(band(root, "active"), "work-item-card-ref")
    .some((node) => node.textContent === "YOK-9"));
  assert.ok(byClass(band(root, "release"), "work-item-card-ref")
    .some((node) => node.textContent === "YOK-11"));
  assert.ok(byClass(band(root, "waiting"), "work-item-card-ref")
    .some((node) => node.textContent === "YOK-13"));

  for (const ref of ["YOK-9", "YOK-11", "YOK-13"]) {
    const minis = byClass(cardFor(root, ref), "item-claimant-mini");
    assert.equal(minis.length, 1, `${ref} should show its holder`);
    assert.match(descendantText(minis[0]), /codex/);
  }

  // The parked release holder reads as parked, in the same chip Active uses,
  // and reveals the full session card on click.
  const releaseCard = cardFor(root, "YOK-11");
  const pill = byClass(releaseCard, "session-status-pill")[0];
  assert.equal(pill.textContent, "parked");
  const preview = byClass(releaseCard, "item-claimant-preview")[0];
  assert.equal(preview.hidden, true);
  byClass(releaseCard, "item-claimant-mini")[0].dispatchEvent(new Event("click"));
  assert.equal(preview.hidden, false);
  assert.equal(byClass(preview, "session-card").length, 1);

  // An unclaimed card has no session box at all.
  const unclaimed = cardFor(root, "YOK-12");
  assert.ok(unclaimed);
  assert.equal(byClass(unclaimed, "item-claimant-row").length, 0);
  mounted.unmount();
});
