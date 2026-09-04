import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sessionModePill, sessionReasonBadge } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_support.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

test("session reason badge keeps quiet context accessible without inline prose", () => {
  const documentNode = new FakeDocument();
  const parked = sessionReasonBadge(
    documentNode, "parked", "waiting on a blocking claim",
  );
  assert.equal(parked.hidden, false);
  assert.equal(parked.textContent, "parked");
  assert.equal(parked.className, "session-reason-badge");
  assert.equal(parked.title, "waiting on a blocking claim");
  assert.equal(parked.tabIndex, 0);
  assert.equal(parked.attributes.get("role"), "note");
  assert.equal(
    parked.attributes.get("aria-label"),
    "parked: waiting on a blocking claim",
  );
  assert.equal(parked.attributes.get("data-reason"), "waiting on a blocking claim");
  const bare = sessionReasonBadge(documentNode, "parked", "");
  assert.equal(bare.textContent, "parked");
  assert.equal(bare.title, undefined);
  assert.equal(bare.tabIndex, -1);
  assert.equal(bare.attributes.has("data-reason"), false);
  const whitespace = sessionReasonBadge(documentNode, "parked", "   ");
  assert.equal(whitespace.attributes.has("data-reason"), false);
  const working = sessionModePill(
    documentNode, "dash", "active", "waiting on merge queue",
  );
  assert.equal(working.hidden, false);
  assert.equal(working.textContent, "reason");
  assert.equal(working.title, "waiting on merge queue");
  assert.equal(working.attributes.get("aria-label"), "reason: waiting on merge queue");
  const silent = sessionModePill(documentNode, "dash", "active", null);
  assert.equal(silent.hidden, true);
  assert.equal(silent.textContent, "");
});

test("reason and sibling pills stay within the shared session palette and row", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-reason-badge \{[^}]*background: var\(--yoke-warn-bg\);[^}]*color: var\(--yoke-warn\);/s,
  );
  assert.match(
    css,
    /\.session-reason-badge\[data-reason\]:focus::after \{[^}]*content: attr\(data-reason\);/s,
  );
  // The lane keeps the shared pill's non-shrinking box so a long lane name
  // moves to the next row of the wrapping identity line instead of squeezing.
  assert.match(
    css,
    /\.session-lane,[\s\S]*?\.session-model-tag \{[^}]*flex: 0 0 auto;/,
  );
  assert.doesNotMatch(css, /\.session-lane \{/);
});
