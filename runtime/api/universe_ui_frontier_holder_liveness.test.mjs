// Parked and gone holders retain custody in Held, not working, with their
// actual reason and session chip. Presence never substitutes for progress.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  claimingSession,
  descendantText,
  workbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountFrontier(session) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: workbenchClient({ homes: { "YOK-9": {
      section: "in_progress", activity: "waiting", reason: session.quiet_reason || "session_process_gone",
    } }, "sessions.list": { rows: [session] } }),
  });
  await settle();
  return { root, mounted };
}

const band = (root, key) => byClass(root, `work-band-${key}`)[0];
const cardsIn = (root, key) => byClass(band(root, key), "work-item-card")
  .map(ownTextContent);

test("a parked holder stays held with its reason and no process chip", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountFrontier({
    ...claimingSession(),
    liveness: "waiting",
    mode: "parked",
    session_state: { status: "waiting", active_at: null, reason: "Waiting for the next turn.", presence: "gone", activity: "silent", intent: { state: "parked" } },
    quiet_reason: "awaiting YOK-9 delivery",
    native_process: { state: "gone", resumable_from_transcript: true },
  });

  assert.equal(cardsIn(root, "active").length, 1);
  assert.match(descendantText(band(root, "active")), /Waiting/);
  assert.doesNotMatch(descendantText(band(root, "active")), /Held, not working/);
  const chip = byClass(band(root, "active"), "item-claimant-mini")[0];
  assert.ok(chip, "the holding session's chip is drawn");
  assert.match(descendantText(chip), /Waiting/);
  assert.equal(byClass(chip, "item-claimant-intent").length, 0);
  assert.equal(byClass(chip, "item-claimant-process").length, 0);
  assert.doesNotMatch(descendantText(root), /Owner unavailable/);
  mounted.unmount();
});

test("a gone holder stays held and still names itself", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountFrontier({
    ...claimingSession(),
    liveness: "stale",
    native_process: { state: "gone" },
  });

  const held = band(root, "active");
  assert.match(descendantText(held), /Waiting/);
  assert.doesNotMatch(descendantText(held), /session process gone/);
  assert.equal(byClass(held, "item-claimant-mini").length, 1);
  mounted.unmount();
});
