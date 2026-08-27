import assert from "node:assert/strict";
import test from "node:test";

import { parkedBadge, sessionModePill } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_support.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

test("parked badge shows the reason and hides every other mode", () => {
  const documentNode = new FakeDocument();
  const parked = parkedBadge(documentNode, "parked", "waiting on YOK-2546");
  assert.equal(parked.hidden, false);
  assert.equal(parked.textContent, "parked · waiting on YOK-2546");
  assert.equal(parked.className, "session-parked-badge");
  const bare = parkedBadge(documentNode, "parked", "");
  assert.equal(bare.textContent, "parked");
  const other = sessionModePill(documentNode, "dash", "active", null);
  assert.equal(other.hidden, true);
  assert.equal(other.textContent, "");
});
