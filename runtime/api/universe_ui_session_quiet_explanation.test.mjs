import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sessionQuietExplanation, sessionStateBadge } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_support.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

test("session state and quiet explanation stay separate", () => {
  const documentNode = new FakeDocument();
  const parked = sessionStateBadge(documentNode, "parked");
  assert.equal(parked.textContent, "parked");
  assert.equal(parked.className, "pill idle");
  assert.equal(parked.attributes.get("data-state"), "parked");
  assert.equal(sessionStateBadge(documentNode, "dash"), null);
  const explanation = sessionQuietExplanation(
    documentNode, "waiting on a blocking claim",
  );
  assert.equal(explanation.tagName, "DETAILS");
  assert.equal(explanation.children[0].tagName, "SUMMARY");
  assert.equal(explanation.children[0].textContent, "Why quiet");
  assert.equal(explanation.children[1].textContent, "waiting on a blocking claim");
  assert.equal(sessionQuietExplanation(documentNode, "   "), null);
  assert.equal(sessionQuietExplanation(documentNode, null), null);
});

test("quiet explanations use a readable native disclosure", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-quiet-summary \{[^}]*min-height: 24px;[^}]*cursor: pointer;[^}]*color: var\(--yoke-warn\);/s,
  );
  assert.match(
    css,
    /\.session-quiet-copy \{[^}]*overflow-wrap: anywhere;[^}]*white-space: pre-wrap;/s,
  );
  // The lane keeps the shared pill's non-shrinking box so a long lane name
  // moves to the next row of the wrapping identity line instead of squeezing.
  assert.match(
    css,
    /\.session-lane,[\s\S]*?\.session-model-tag \{[^}]*flex: 0 0 auto;/,
  );
  assert.doesNotMatch(css, /\.session-lane \{/);
});
