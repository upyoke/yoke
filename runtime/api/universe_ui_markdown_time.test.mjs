import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMarkdown,
} from "../../packages/yoke-core/src/yoke_core/ui/static/markdown_view.js";
import {
  relativeTime,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";
import {
  FakeDocument,
  allNodes,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

test("safe Markdown renders hierarchy, inline meaning, and checklist state", () => {
  const documentNode = new FakeDocument();
  const body = renderMarkdown(documentNode, [
    "# WORKFLOW-TYPES",
    "<!-- render metadata stays hidden -->",
    "Use **one authority** and `yoke`.",
    "",
    "1. Render",
    "2. Review",
    "",
    "- [x] Contract verified",
    "- [ ] Visual inspection",
    "",
    "[unsafe](javascript:alert(1))",
  ].join("\n"), {
    omitLeadingHeading: ["WORKFLOW-TYPES"],
    demoteHeadings: true,
  });
  const nodes = allNodes(body);

  assert.equal(nodes.some((node) => /^H[1-6]$/.test(node.tagName)), false);
  assert.ok(nodes.some((node) => node.tagName === "STRONG"));
  assert.ok(nodes.some((node) => node.tagName === "CODE"));
  assert.ok(nodes.some((node) => node.tagName === "OL"));
  assert.equal(byClass(body, "rich-check").length, 2);
  assert.equal(byClass(body, "rich-check").filter(
    (node) => node.classList.contains("complete"),
  ).length, 1);
  assert.equal(nodes.some((node) => node.tagName === "A"), false);
  assert.equal(nodes.some((node) => node.innerHTML), false);
  assert.doesNotMatch(
    nodes.map((node) => node.textContent).join(" "),
    /render metadata/,
  );
});

test("relative timestamps expose absolute context and toggle in place", () => {
  const documentNode = new FakeDocument();
  const now = Date.now();
  const value = new Date(now - (5 * 60 * 1000)).toISOString();
  const time = relativeTime(documentNode, value, now);

  assert.equal(time.tagName, "TIME");
  assert.equal(time.className, "ago");
  assert.equal(time.textContent, "5m");
  assert.equal(time.attributes.get("role"), "button");
  assert.equal(time.attributes.get("aria-pressed"), "false");
  assert.equal(time.attributes.get("datetime"), value);
  assert.equal(time.attributes.get("data-ms"), String(new Date(value).getTime()));
  assert.ok(time.title);

  time.dispatchEvent(new Event("click"));
  assert.equal(time.textContent, time.title);
  assert.equal(time.attributes.get("aria-pressed"), "true");
  time.dispatchEvent(new Event("click"));
  assert.notEqual(time.textContent, time.title);
  const key = new Event("keydown");
  key.key = "Enter";
  time.dispatchEvent(key);
  assert.equal(time.textContent, time.title);
});
