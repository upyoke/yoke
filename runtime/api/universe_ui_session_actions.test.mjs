// A session's card answers what it is doing; this panel answers who did
// something TO it. Each row names the action, the actor who took it, and —
// when the control plane refused — that somebody tried and was turned away.
import assert from "node:assert/strict";
import test from "node:test";

import {
  actionFact,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_actions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function factFor(row) {
  return actionFact(new FakeDocument(), {
    created_at: "2026-08-22T16:00:00Z",
    event_outcome: "completed",
    ...row,
  });
}

test("an action names itself and the actor who took it", () => {
  const fact = factFor({ context_label: "wake", source_label: "Ada" });
  assert.equal(byClass(fact, "labelled-fact-label")[0].textContent, "wake");
  assert.match(byClass(fact, "labelled-fact-value")[0].textContent, /^by Ada/);
});

test("a refused action still reads as an attempt somebody made", () => {
  const fact = factFor({
    context_label: "terminate",
    source_label: "Grace",
    event_outcome: "failed",
  });
  assert.equal(
    byClass(fact, "labelled-fact-label")[0].textContent,
    "terminate — refused",
  );
});

test("an action with no resolvable actor says so rather than going blank", () => {
  const fact = factFor({ context_label: "message", source_label: "" });
  assert.match(byClass(fact, "labelled-fact-value")[0].textContent, /^by unknown/);
});
