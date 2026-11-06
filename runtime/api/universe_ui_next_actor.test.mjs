import assert from "node:assert/strict";
import test from "node:test";
import { appendNextActor, nextActorText } from "../../packages/yoke-core/src/yoke_core/ui/static/next_actor_display.js";
import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { workItemCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

test("session and Frontier cards show the same named person and waiting reason", () => {
  const doc = new FakeDocument();
  const next_actor = { actor: "operator", reason: "approve secret", since: "2026-11-06T12:00:00Z", people: [{ name: "Reviewer" }] };
  const session = sessionCard(doc, { session_id: "worker", liveness: "waiting", mode: "parked", claims: [], next_actor }, () => {});
  const item = workItemCard(doc, { public_ref: "item", title: "Title", status: "implementing", next_actor }, "all");
  for (const card of [session, item]) {
    const line = byClass(card, "next-actor")[0];
    assert.equal(line.textContent, "Next: Reviewer · approve secret");
    assert.equal(line.title, "Since 2026-11-06T12:00:00Z");
  }
});

test("older server rows degrade without invented responsibility", () => {
  const doc = new FakeDocument();
  const host = doc.createElement("div");
  appendNextActor(doc, host, undefined);
  assert.equal(host.children.length, 0);
  assert.equal(nextActorText({ actor: "another_item", reason: "dependency_unsatisfied" }), "Next: another item · dependency unsatisfied");
});
