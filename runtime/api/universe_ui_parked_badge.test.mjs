import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parkedBadge, sessionModePill } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_support.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

test("parked badge keeps its reason accessible without rendering it inline", () => {
  const documentNode = new FakeDocument();
  const parked = parkedBadge(documentNode, "parked", "waiting on YOK-2546");
  assert.equal(parked.hidden, false);
  assert.equal(parked.textContent, "parked");
  assert.equal(parked.className, "session-parked-badge");
  assert.equal(parked.title, "waiting on YOK-2546");
  assert.equal(parked.tabIndex, 0);
  assert.equal(parked.attributes.get("role"), "note");
  assert.equal(parked.attributes.get("aria-label"), "parked: waiting on YOK-2546");
  assert.equal(parked.attributes.get("data-reason"), "waiting on YOK-2546");
  const bare = parkedBadge(documentNode, "parked", "");
  assert.equal(bare.textContent, "parked");
  assert.equal(bare.title, undefined);
  assert.equal(bare.tabIndex, -1);
  assert.equal(bare.attributes.has("data-reason"), false);
  const whitespace = parkedBadge(documentNode, "parked", "   ");
  assert.equal(whitespace.attributes.has("data-reason"), false);
  const other = sessionModePill(documentNode, "dash", "active", null);
  assert.equal(other.hidden, true);
  assert.equal(other.textContent, "");
});

test("parked and sibling pills stay within the shared session palette and row", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-parked-badge \{[^}]*background: var\(--yoke-warn-bg\);[^}]*color: var\(--yoke-warn\);/s,
  );
  assert.match(
    css,
    /\.session-parked-badge\[data-reason\]:focus::after \{[^}]*content: attr\(data-reason\);/s,
  );
  assert.match(
    css,
    /\.session-lane \{[^}]*flex: 0 1 auto;[^}]*text-overflow: ellipsis;/s,
  );
});
