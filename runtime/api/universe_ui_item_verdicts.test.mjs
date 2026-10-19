import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import { FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

async function renderedText(item) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderItemDetailView(itemContext(documentNode, async (request) => ({
    status: 200,
    envelope: {
      success: true,
      result: request.function === "items.detail.get"
        ? { item }
        : { tasks: [] },
    },
  })), root, "7", "ACM-22");
  await settle();
  return itemText(root);
}

test("an epic without verdicts says none is recorded", async () => {
  const epic = detailItem("epic");
  epic.shepherd_verdicts = [];

  const rendered = await renderedText(epic);

  assert.match(rendered, /Shepherd verdicts/);
  assert.match(rendered, /No shepherd verdict recorded\./);
});

test("a non-epic item shows verdicts only when it has them", async () => {
  const dash = detailItem("dash");
  assert.doesNotMatch(await renderedText(dash), /Shepherd verdicts/);

  dash.shepherd_verdicts = [{
    transition: "refined_to_planned",
    worker: "boss",
    verdict: "READY",
    attempt: 2,
    caveats: "",
    created_at: "2026-04-03T14:37:32.000000Z",
  }];
  const rendered = await renderedText(dash);

  assert.match(rendered, /Shepherd verdicts/);
  assert.match(rendered, /refined_to_planned · 2026-04-03/);
  assert.match(rendered, /READY\s+· boss · attempt 2/);
});
