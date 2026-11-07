import assert from "node:assert/strict";
import test from "node:test";
import { appendNextActor, nextActorText } from "../../packages/yoke-core/src/yoke_core/ui/static/next_actor_display.js";
import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { workItemCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

test("cards render the server sentence once and keep the code behind info", () => {
  const doc = new FakeDocument();
  const reason = "Waiting for the release to finish.";
  const next_actor = {actor: "ci_or_deploy", reason: "release_run_in_progress", sentence: reason};
  const session = sessionCard(doc, {session_state: {status: "waiting", active_at: null, reason, next_actor}}, () => {});
  const item = workItemCard(doc, {public_ref: "item", next_actor}, "all");
  for (const card of [session, item]) {
    assert.equal(card.textContent.split(reason).length - 1, 1);
    assert.doesNotMatch(card.textContent, /release_run_in_progress/);
  }
  assert.match(byClass(item, "tooltip-info")[0].getAttribute("data-tooltip"), /release_run_in_progress/);
});

test("older server rows request an upgrade without expanding reason codes", () => {
  const doc = new FakeDocument();
  const host = doc.createElement("div");
  appendNextActor(doc, host, undefined);
  assert.equal(host.children.length, 0);
  assert.equal(nextActorText({actor: "another_item", reason: "dependency_unsatisfied"}),
    "Next: refresh after the server upgrade.");
});
