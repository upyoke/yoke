import assert from "node:assert/strict";
import test from "node:test";
import { renderLevelsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_levels.js";
import { FakeDocument, allNodes, byClass, visibleText, settle } from "./universe_ui_dom_test_support.mjs";

const CAPACITY = {
  levels: [
    { name: "JUNIOR", glyph: "🐥", launchable_surfaces: ["cursor-cli", "codex-cli"],
      options: [{ model: "grok-4.7", display_name: "Grok 4.7", min_effort: "high", now: { state: "can_launch" } }] },
    { name: "PRINCIPAL", glyph: "🦅", launchable_surfaces: [],
      options: [{ model: "gpt-6-astra", display_name: "GPT-6 Astra", min_effort: "xhigh", now: { state: "blocked", blockers: [{ label: "Codex weekly pool exhausted; wait for its reset." }] } }] },
  ],
  cursor_quota_order: ["Cursor Models", "Other Models"],
};

async function mount(result = CAPACITY, handlers = {}) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const context = { document: documentNode, isMounted: () => true, client: {
    async call(request) {
      requests.push(request);
      if (handlers[request.function]) return handlers[request.function](request);
      return { status: 200, envelope: { success: true, result } };
    },
  } };
  await renderLevelsView(context, main);
  return { main, requests, context };
}

test("Levels renders exactly the four requested columns", async () => {
  const { main } = await mount();
  const table = byClass(main, "level-options")[0];
  assert.deepEqual(allNodes(table).filter((node) => node.tagName === "TH").map((node) => node.textContent), ["#", "MODEL", "MIN EFFORT", "NOW"]);
  const text = visibleText(main, " ");
  for (const value of ["grok-4.7", "Grok 4.7", "high", "Can launch", "Launchable on", "cursor-cli"]) assert.ok(text.includes(value));
  for (const retired of ["Next launch in", "Draws on", "View only", "Project overrides", "exhausted →"]) assert.ok(!text.includes(retired));
});

test("blocked rows retain the named recovery", async () => {
  const { main } = await mount();
  assert.ok(visibleText(main, " ").includes("Codex weekly pool exhausted; wait for its reset."));
});

test("Cursor quota order has exactly two ordered rows", async () => {
  const { main } = await mount();
  const table = byClass(main, "cursor-quota-order")[0];
  const rows = allNodes(table).filter((node) => node.tagName === "TR");
  assert.equal(rows.length, 2);
  assert.ok(visibleText(rows[0], " ").includes("1 Cursor Models"));
  assert.ok(visibleText(rows[1], " ").includes("2 Other Models"));
  assert.equal(byClass(main, "quota-order-move").length, 2);
});

test("reordering calls the bounded universe setter and refreshes capacity", async () => {
  let pools = [...CAPACITY.cursor_quota_order];
  const { main, requests } = await mount(CAPACITY, {
    "universe.cursor_quota_order.set": (request) => {
      pools = request.payload.pools;
      return { status: 200, envelope: { success: true, result: { pools } } };
    },
    "universe.level_capacity.get": () => ({ status: 200, envelope: { success: true, result: { ...CAPACITY, cursor_quota_order: pools } } }),
  });
  byClass(main, "quota-order-move")[1].dispatchEvent(new Event("click"));
  await settle();
  const write = requests.find((request) => request.function === "universe.cursor_quota_order.set");
  assert.deepEqual(write.payload, { pools: ["Other Models", "Cursor Models"] });
  assert.ok(visibleText(byClass(main, "cursor-quota-order")[0], " ").includes("1 Other Models"));
});

test("setter refusal stays visible and restores the controls", async () => {
  const { main } = await mount(CAPACITY, { "universe.cursor_quota_order.set": () => ({
    status: 403, envelope: { success: false, error: { message: "org_admin_required: ask an org admin to set Cursor order." } },
  }) });
  byClass(main, "quota-order-move")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.ok(visibleText(main, " ").includes("org_admin_required"));
  assert.ok(byClass(main, "quota-order-move").every((button) => !button.disabled));
});

test("an old serving response names the schema recovery", async () => {
  const { main } = await mount({ levels: CAPACITY.levels });
  assert.ok(visibleText(main, " ").includes("levels_schema_version_skew"));
  assert.equal(byClass(main, "quota-order-move").length, 0);
});
