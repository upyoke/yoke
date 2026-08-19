import assert from "node:assert/strict";
import test from "node:test";

import {
  itemDrillInHref,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_routes.js";

test("item drill-in routes pair a sequence with its numeric project", () => {
  assert.equal(itemDrillInHref({
    projectId: 1,
    projectSequence: 2228,
  }), "#/items/2228?project=1");
  assert.equal(itemDrillInHref({
    projectId: "1",
    publicRef: "YOK-2228",
  }), "#/items/2228?project=1");
});

test("item drill-in routes reject ambient and internal identities", () => {
  assert.equal(itemDrillInHref({
    projectId: "yoke",
    publicRef: "YOK-2228",
  }), null);
  assert.equal(itemDrillInHref({
    projectId: 1,
    publicRef: "2262",
  }), null);
  assert.equal(itemDrillInHref({
    projectId: 1,
    itemId: 2262,
  }), null);
  assert.equal(itemDrillInHref({
    projectId: 1,
    projectSequence: 2228,
    publicRef: "YOK-2262",
  }), null);
});
