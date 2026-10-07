// The Waiting graph's model against the six states it must draw: columns and
// their headings, tile order, edges and the longest chain, stuck and
// deadlock copy, fan-out stacks, On hold, the project filter, and the empty
// state. The DOM rendering of the same states is pinned in
// universe_ui_frontier_graph_render.test.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import {
  frontierColumnHeading,
  frontierColumnPlan,
  frontierFilter,
  frontierGraphColumns,
  frontierTileMeta,
  frontierWaitingSplit,
} from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_dependency_model.js";
import { state, stateModel } from "./frontier_dependency_states.mjs";

function columns(model) {
  return frontierGraphColumns(model).map((col, c) => ({
    heading: frontierColumnHeading(c),
    tiles: frontierColumnPlan(col.filter((n) => !n.cycle)).map((entry) => (
      entry.kind === "tile" ? entry.ref : `+${entry.refs.length} more`
    )),
    deadlocked: col.filter((n) => n.cycle).map((n) => n.ref),
  }));
}

function criticalEdges(model) {
  return model.edges
    .filter((e) => model.critical.has(e.from) && model.critical.has(e.to))
    .map((e) => `${e.from}>${e.to}`);
}

const byPrefix = (...prefixes) => (node) => prefixes.includes(node.ref.split("-")[0]);

test("today: two chains, all start gates, the longest one drawn heavier", () => {
  const model = stateModel(state("today"));
  assert.deepEqual(columns(model), [
    { heading: "Holding work up", tiles: ["YOK-3717", "YOK-3757"], deadlocked: [] },
    { heading: "1 step behind", tiles: ["YOK-3718", "YOK-3725", "YOK-3758"], deadlocked: [] },
    { heading: "2 steps behind", tiles: ["YOK-3719", "YOK-3722", "YOK-3723", "PLAT-188"], deadlocked: [] },
    { heading: "3 steps behind", tiles: ["YOK-3720"], deadlocked: [] },
    { heading: "4 steps behind", tiles: ["YOK-3721"], deadlocked: [] },
  ]);
  assert.equal(model.edges.length, 9);
  assert.deepEqual(criticalEdges(model), [
    "YOK-3720>YOK-3721", "YOK-3719>YOK-3720", "YOK-3718>YOK-3719", "YOK-3717>YOK-3718",
  ]);
  assert.equal(frontierTileMeta(model.nodes.get("PLAT-188")), "Starts after YOK-3758 merges");
  assert.equal(model.nodes.get("YOK-3717").unblocks, 7);
  // The frozen item nothing waits on is On hold, not in the graph.
  const { held, graphCount } = frontierWaitingSplit(model);
  assert.deepEqual(held.map((n) => n.ref), ["PLAT-143"]);
  assert.equal(graphCount, 9);
});

test("today: the Platform filter keeps the Yoke chain its item waits on", () => {
  const model = frontierFilter(stateModel(state("today")), byPrefix("PLAT"));
  assert.ok(model.nodes.has("YOK-3757"));
  assert.ok(model.nodes.has("YOK-3758"));
  assert.ok(model.nodes.has("PLAT-188"));
  // Yoke work with no link to Platform drops out of every band.
  assert.equal(model.nodes.has("YOK-3717"), false);
  assert.equal(model.nodes.has("YOK-3750"), false);
  assert.deepEqual(columns(model).map((col) => col.tiles), [
    ["YOK-3757"], ["YOK-3758"], ["PLAT-188"],
  ]);
  const { held, graphCount } = frontierWaitingSplit(model);
  assert.deepEqual(held.map((n) => n.ref), ["PLAT-143"]);
  assert.equal(graphCount, 2);
});

test("busy week: fan-in and diamonds sit by their deepest blocker", () => {
  const model = stateModel(state("busy"));
  const cols = columns(model);
  assert.deepEqual(cols.map((col) => col.heading), [
    "Holding work up", "1 step behind", "2 steps behind", "3 steps behind",
    "4 steps behind", "5 steps behind", "6 steps behind",
  ]);
  assert.deepEqual(cols[0].tiles, ["YOK-3801", "PLAT-201", "YOK-3760", "YOK-3790", "BUZ-140"]);
  assert.deepEqual(cols[1].tiles, [
    "YOK-3802", "PLAT-202", "YOK-3762", "YOK-3761", "YOK-3763", "YOK-3791", "YOK-3792", "YOK-3795",
  ]);
  assert.deepEqual(cols[2].tiles, ["YOK-3803", "YOK-3804", "PLAT-203", "PLAT-205", "YOK-3793", "PLAT-206"]);
  assert.equal(model.edges.length, 24);
  assert.deepEqual(criticalEdges(model), [
    "YOK-3801>YOK-3802", "YOK-3802>YOK-3804", "YOK-3804>YOK-3807",
    "YOK-3807>YOK-3808", "YOK-3808>YOK-3809", "YOK-3809>PLAT-204",
  ]);
  assert.equal(frontierTileMeta(model.nodes.get("YOK-3793")), "Waits on 2 items");
  const { held, graphCount } = frontierWaitingSplit(model);
  assert.deepEqual(held.map((n) => n.ref), ["YOK-3770"]);
  assert.equal(graphCount, 21);
});

test("every gate and condition reads as its own phrase", () => {
  const model = stateModel(state("gates"));
  const meta = (ref) => frontierTileMeta(model.nodes.get(ref));
  assert.equal(meta("YOK-3821"), "Can build now · lands after YOK-3820 merges");
  assert.equal(meta("YOK-3822"), "Starts after YOK-3820 is done");
  assert.equal(meta("YOK-3824"), "Starts after YOK-3822 reaches release");
  assert.equal(meta("PLAT-211"), "Starts after PLAT-210 is live on prod");
  assert.equal(meta("YOK-3823"), "Can't close until PLAT-210 is live on prod");
  assert.deepEqual(columns(model).map((col) => col.tiles), [
    ["YOK-3820", "PLAT-210", "YOK-3827"],
    ["YOK-3822", "YOK-3821", "YOK-3826", "PLAT-211", "YOK-3823", "YOK-3828"],
    ["YOK-3824"],
  ]);
  assert.equal(model.edges.length, 7);
  // Two steps is not a chain worth emphasising over the others; three is.
  assert.deepEqual(criticalEdges(model), ["YOK-3820>YOK-3822", "YOK-3822>YOK-3824"]);
  assert.deepEqual(frontierWaitingSplit(model).held, []);
});

test("stuck, broken and deadlocked chains say why on their own tiles", () => {
  const model = stateModel(state("stuck"));
  const stuck = (ref) => model.nodes.get(ref).stuck;
  assert.equal(stuck("YOK-3830"), "Frozen by ben");
  assert.equal(model.nodes.get("YOK-3830").stall, "Frozen by ben");
  assert.equal(stuck("YOK-3833"), "Stuck upstream: YOK-3831");
  assert.equal(stuck("YOK-3841"), "YOK-3840 was cancelled — it will never merge");
  assert.equal(stuck("PLAT-221"),
    "prod is not in PLAT-220's delivery flow, so it can never be live there");
  assert.equal(stuck("YOK-3850"), "Blocked — waiting on an AWS quota increase");
  assert.equal(stuck("YOK-3860"), "Deadlock — YOK-3861 ⇄ YOK-3860 wait on each other");
  assert.equal(stuck("YOK-3862"), "Stuck upstream: YOK-3861");
  const cols = columns(model);
  assert.deepEqual(cols[0], {
    heading: "Holding work up",
    tiles: ["YOK-3830", "YOK-3850", "BUZ-90", "PLAT-220", "YOK-3840", "YOK-3880"],
    deadlocked: ["YOK-3860", "YOK-3861"],
  });
  assert.equal(model.edges.length, 12);
  // A stuck chain is raised as stuck, never as the longest one.
  assert.deepEqual(criticalEdges(model), []);
  // The cancelled blocker is not on this Frontier; it is a terminal ghost.
  assert.equal(model.nodes.get("YOK-3840").band, "off");
  assert.equal(model.nodes.get("YOK-3840").terminal, true);
});

test("stuck: the Platform filter keeps the Buzz blocker its item waits on", () => {
  const model = frontierFilter(stateModel(state("stuck")), byPrefix("PLAT"));
  assert.deepEqual([...model.nodes.keys()].sort(), ["BUZ-90", "PLAT-220", "PLAT-221", "PLAT-225"]);
});

test("wide: fourteen leaves on one blocker fold after the fifth", () => {
  const model = stateModel(state("wide"));
  const cols = columns(model);
  assert.equal(cols.length, 2);
  assert.deepEqual(cols[1].tiles, [
    "YOK-3901", "YOK-3902", "YOK-3903", "YOK-3904", "YOK-3905", "+9 more",
    "YOK-3926", "PLAT-231", "YOK-3921", "YOK-3923", "YOK-3925", "YOK-3928",
  ]);
  const col = frontierGraphColumns(model)[1];
  const stack = frontierColumnPlan(col).find((entry) => entry.kind === "stack");
  assert.deepEqual(stack.refs, Array.from({ length: 9 }, (_, i) => `YOK-${3906 + i}`));
  assert.equal(stack.phrase, "Starts after YOK-3900 merges");
  assert.equal(model.nodes.get("YOK-3900").unblocks, 14);
  assert.equal(model.edges.length, 20);
  assert.deepEqual(criticalEdges(model), []);
});

test("nothing waiting draws no graph and holds nothing", () => {
  const model = stateModel(state("empty"));
  assert.equal(model.linked.length, 0);
  assert.deepEqual(frontierGraphColumns(model), []);
  const { held, graphCount } = frontierWaitingSplit(model);
  assert.deepEqual(held, []);
  assert.equal(graphCount, 0);
});
