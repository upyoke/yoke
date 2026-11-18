// The header search hint names the modifier the operator's keyboard has.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument } from "./universe_ui_dom_test_support.mjs";
import {
  createSearchDialog,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_search_overlay.js";

function hintOn(navigatorNode) {
  const documentNode = new FakeDocument();
  documentNode.body = documentNode.createElement("body");
  documentNode.defaultView.navigator = navigatorNode;
  const { root } = createSearchDialog(documentNode, "shortcut", () => {});
  return byClass(root, "header-search-key")[0].textContent;
}

test("Linux and Windows read Ctrl K", () => {
  assert.equal(hintOn({ platform: "Linux x86_64" }), "Ctrl K");
  assert.equal(hintOn({ userAgentData: { platform: "Linux" } }), "Ctrl K");
  assert.equal(hintOn({ userAgentData: { platform: "Windows" } }), "Ctrl K");
  assert.equal(hintOn({ platform: "Win32" }), "Ctrl K");
});

test("Mac reads ⌘K", () => {
  assert.equal(hintOn({ platform: "MacIntel" }), "⌘K");
  assert.equal(hintOn({ userAgentData: { platform: "macOS" } }), "⌘K");
});

test("no navigator reads Ctrl K", () => {
  assert.equal(hintOn(undefined), "Ctrl K");
});
