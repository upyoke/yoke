import assert from "node:assert/strict";
import test from "node:test";

import {
  FakeDocument,
  cellText,
  ownTextContent,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";

test("textContent aggregates descendant text in DOM order", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const emphasis = documentNode.createElement("strong");
  emphasis.textContent = "important";
  const detail = documentNode.createElement("span");
  detail.textContent = " detail";
  emphasis.appendChild(detail);

  root.replaceChildren(
    documentNode.createTextNode("prefix "),
    emphasis,
    documentNode.createTextNode(" suffix"),
  );

  assert.equal(root.textContent, "prefix important detail suffix");
  assert.equal(visibleText(root), "prefix important detail suffix");
  assert.equal(ownTextContent(root), "");
  assert.equal(ownTextContent(emphasis), "important");
});

test("setting textContent replaces existing descendants", () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const child = documentNode.createElement("span");
  child.textContent = "old";
  root.appendChild(child);

  root.textContent = "replacement";

  assert.equal(root.textContent, "replacement");
  assert.equal(root.children.length, 0);
  assert.equal(child.parentNode, null);
});

test("cellText reads a primary value through presentation wrappers", () => {
  const documentNode = new FakeDocument();
  const cell = documentNode.createElement("td");
  const link = documentNode.createElement("a");
  link.textContent = "primary";
  const detail = documentNode.createElement("span");
  detail.textContent = "detail";
  link.appendChild(detail);
  cell.appendChild(link);

  assert.equal(cell.textContent, "primarydetail");
  assert.equal(cellText(cell), "primary");
});
