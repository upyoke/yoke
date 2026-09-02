import assert from "node:assert/strict";
import test from "node:test";

import {
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  renderInbox,
} from "./universe_ui_inbox_test_support.mjs";

test("Inbox labels row-owned projects only for merged scope", async () => {
  const merged = renderInbox();
  await settle();
  assert.deepEqual(
    byClass(merged.main, "inbox-row-project").map(
      (node) => node.textContent,
    ),
    ["yoke"],
  );

  const narrowed = renderInbox(["10"]);
  await settle();
  assert.equal(byClass(narrowed.main, "inbox-row-project").length, 0);
});
