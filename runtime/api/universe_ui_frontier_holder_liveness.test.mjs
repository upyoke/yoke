// A Frontier card always names who holds its item, and calls the owner
// unavailable only when that owner is abandoned: not parked, its process
// gone, and quiet past its activity window. A parked holder is waiting on
// purpose — a deploy, a landing — and the next message resumes it from its
// transcript even after its process has exited.

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
    client: workbenchClient({ "sessions.list": { rows: [session] } }),
  });
  await settle();
  return { root, mounted };
}

const band = (root, key) => byClass(root, `work-band-${key}`)[0];
const cardsIn = (root, key) => byClass(band(root, key), "work-item-card")
  .map(ownTextContent);

test("a parked holder whose process exited stays active with its chip", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountFrontier({
    ...claimingSession(),
    liveness: "waiting",
    mode: "parked",
    quiet_reason: "awaiting YOK-9 delivery",
    native_process: { state: "gone", resumable_from_transcript: true },
  });

  assert.equal(cardsIn(root, "active").length, 1);
  const chip = byClass(band(root, "active"), "item-claimant-mini")[0];
  assert.ok(chip, "the holding session's chip is drawn");
  assert.match(descendantText(chip), /process exited/);
  assert.doesNotMatch(descendantText(root), /Owner unavailable/);
  mounted.unmount();
});

test("an abandoned holder is unavailable and still names itself", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountFrontier({
    ...claimingSession(),
    liveness: "stale",
    native_process: { state: "gone" },
  });

  assert.deepEqual(cardsIn(root, "active"), []);
  const held = band(root, "hold");
  assert.match(descendantText(held), /Owner unavailable/);
  assert.equal(byClass(held, "item-claimant-mini").length, 1);
  mounted.unmount();
});
