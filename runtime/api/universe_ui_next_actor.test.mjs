import assert from "node:assert/strict";
import test from "node:test";
import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { workItemCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

test("session reasons and next actor appear only in details; work cards omit them", () => {
  const doc = new FakeDocument();
  const reason = "Waiting for the release to finish.";
  const next_actor = {actor: "ci_or_deploy", reason: "release_run_in_progress", sentence: reason};
  const session = sessionCard(doc, {session_state: {status: "waiting", active_at: null, reason, next_actor}}, () => {});
  const item = workItemCard(doc, {public_ref: "item", next_actor}, "all");
  for (const card of [session, item]) {
    assert.doesNotMatch(card.textContent, /Waiting for the release|release_run_in_progress|Next actor/);
    assert.equal(byClass(card, "next-actor").length, 0);
    assert.equal(byClass(card, "session-reason").length, 0);
  }
  const details = byClass(session, "session-details")[0].getAttribute("data-tooltip");
  assert.match(details, /Reason: Waiting for the release to finish/);
  assert.match(details, /Next actor: ci_or_deploy · release_run_in_progress/);
});
