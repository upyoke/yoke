import assert from "node:assert/strict";
import test from "node:test";
import { frontierBandRows } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_band_rows.js";
import { frontierGraphModel } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_graph_nodes.js";
import { frontierWaitingSplit } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_dependency_model.js";
import { frontierTile } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_graph_tiles.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const item = (ref, section, activity = null) => ({
  public_ref: ref, title: ref, project_id: 1, project_sequence: Number(ref.split("-").at(-1)),
  frontier_group: { section, activity, reason: "awaiting_direction" },
  next_actor: { actor: "parent_or_steering", reason: "awaiting_direction" },
});

test("home membership and counts stay exclusive across the full chain", () => {
  const items = [item("I-1", "in_progress", "held"), item("I-2", "waiting"), item("I-3", "on_hold")];
  const rows = frontierBandRows({ items, readyRows: [], blockedRows: [], sessionRows: [] });
  const edges = [
    { blocking_item: "I-1", dependent_item: "I-2", gate_point: "activation", satisfaction: "status:done" },
    { blocking_item: "I-2", dependent_item: "I-3", gate_point: "integration", satisfaction: "fact:merged" },
  ];
  const model = frontierGraphModel(rows, edges, () => "");
  assert.equal(model.linked.length, 3);
  assert.equal(frontierWaitingSplit(model).graphCount, 1);
  assert.equal(frontierWaitingSplit(model).held.length, 1);
  assert.equal(rows.active.length + rows.waiting.length + rows.held.length, items.length);
  assert.equal(model.nodes.get("I-1").reference, true);
  assert.equal(model.nodes.get("I-2").reference, false);
  const tile = frontierTile(new FakeDocument(), model, "I-1", { claimantFor: () => null });
  assert.equal(tile.classList.contains("is-reference"), true);
  assert.equal(byClass(tile, "fdv-tile-ref")[0].href, "#frontier-home-I-1");
  assert.match(byClass(tile, "fdv-reference-home")[0].textContent, /In progress.*Held, not working/);
  assert.match(byClass(tile, "next-actor")[0].textContent, /Next: parent or steering/);
});

test("missing server projection names the required recovery", () => {
  assert.throws(() => frontierBandRows({ items: [{ public_ref: "I-1" }], readyRows: [], blockedRows: [], sessionRows: [] }), /frontier_group_unavailable.*Update/);
});
