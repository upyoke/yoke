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
  next_actor: { actor: "parent_or_steering", sentence: "Waiting for direction.", reason: "awaiting_direction" },
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
  assert.match(byClass(tile, "fdv-reference-home")[0].textContent, /In progress.*Waiting/);
  assert.match(byClass(tile, "next-actor")[0].textContent, /Next: parent or steering/);
});

test("reference tiles stay opaque over graph lines while off-band tiles keep their states", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../../packages/yoke-core/src/yoke_core/ui/static/frontier_graph.css", import.meta.url), "utf8");
  const rules = [...css.matchAll(/\.universe-app-root \.fdv-tile((?:\.[\w-]+)*)\{([^}]*)\}/g)];
  const resolve = (...classes) => {
    const style = {};
    for (const [, modifiers, body] of rules) {
      if (!modifiers.split(".").filter(Boolean).every((name) => classes.includes(name))) continue;
      for (const [, name, value] of body.matchAll(/([\w-]+):([^;]+)/g)) {
        if (name === "border") style["border-style"] = value.split(" ")[1];
        else style[name] = value;
      }
    }
    return style;
  };
  assert.equal(resolve("is-reference").background, "var(--yoke-surface)");
  assert.equal(resolve("is-reference", "is-stall").background, "var(--yoke-crit-bg)");
  for (const state of ["is-ghost", "is-dead"]) {
    assert.deepEqual([resolve("is-reference", state).background, resolve("is-reference", state)["border-style"]], ["transparent", "dashed"]);
  }
  assert.equal(resolve("is-reference", "is-dead")["border-left-color"], "var(--yoke-crit)");
});

test("missing server projection names the required recovery", () => {
  assert.throws(() => frontierBandRows({ items: [{ public_ref: "I-1" }], readyRows: [], blockedRows: [], sessionRows: [] }), /frontier_group_unavailable.*Update/);
});


test("a Done reference beyond the display limit still has a reachable home card", async (t) => {
  const { mountUniverseApp } = await import("../../packages/yoke-core/src/yoke_core/ui/static/app.js");
  const { workbenchClient } = await import("./universe_ui_workbench_test_support.mjs");
  const { response, settle } = await import("./universe_ui_dom_test_support.mjs");
  const saved = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = saved; });
  const done = Array.from({ length: 10 }, (_, index) => ({
    ...item(`I-${index + 1}`, "done"), terminal: true, finished: true,
    finished_at: new Date(Date.now() - index * 60000).toISOString(),
  }));
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=all";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient({
    "items.overview.list": { rows: [...done, item("I-11", "waiting")] },
    "frontier.list": { ready_rows: [], blocked_rows: [], dependency_edges: [{
      blocking_item: "I-10", dependent_item: "I-11", gate_point: "activation", satisfaction: "fact:merged",
    }] },
    "sessions.list": { rows: [] },
  }) });
  t.after(() => mounted.unmount());
  await settle();
  const doneBand = byClass(root, "work-band-done")[0];
  assert.equal(byClass(doneBand, "work-band-count")[0].textContent, "10");
  const homes = byClass(doneBand, "work-item-card").filter((card) => !card.classList.contains("see-more-card"));
  assert.equal(homes.length, 9);
  assert.equal(byClass(doneBand, "see-more-card").length, 1);
  assert.ok(homes.some((card) => card.id === "frontier-home-I-10"));
  const reference = byClass(root, "fdv-tile").find((tile) => tile.getAttribute("data-fdv-ref") === "I-10");
  assert.equal(byClass(reference, "fdv-tile-ref")[0].href, "#frontier-home-I-10");
});

for (const count of [0, 3, 8, 10]) {
  for (const scope of ["all", "1"]) {
    test(`Done history link persists with ${count} finishes in scope ${scope}`, async (t) => {
      const { mountUniverseApp } = await import("../../packages/yoke-core/src/yoke_core/ui/static/app.js");
      const { workbenchClient } = await import("./universe_ui_workbench_test_support.mjs");
      const { response, settle } = await import("./universe_ui_dom_test_support.mjs");
      const saved = globalThis.fetch;
      globalThis.fetch = () => response(200, {});
      t.after(() => { globalThis.fetch = saved; });
      const done = Array.from({ length: count }, (_, index) => ({
        ...item(`I-${index + 1}`, "done"), terminal: true, finished: true,
        finished_at: new Date(Date.now() - index * 60000).toISOString(),
      }));
      const documentNode = new FakeDocument();
      documentNode.defaultView.location.href = `/frontier?project=${scope}`;
      const root = documentNode.createElement("div");
      const mounted = mountUniverseApp(root, { client: workbenchClient({
        "items.overview.list": { rows: done },
        "frontier.list": { ready_rows: [], blocked_rows: [], dependency_edges: [] },
        "sessions.list": { rows: [] },
      }) });
      t.after(() => mounted.unmount());
      await settle();
      const doneBand = byClass(root, "work-band-done")[0];
      assert.equal(byClass(doneBand, "work-band-title")[0].textContent, "Done (24h)");
      assert.equal(byClass(doneBand, "work-band-count")[0].textContent, String(count));
      const links = byClass(doneBand, "see-more-card");
      assert.equal(links.length, 1);
      assert.equal(links[0].href, scope === "all" ? "/items" : "/items?project=1");
      assert.equal(links[0].getAttribute("aria-label"), "See more...");
      const cards = byClass(doneBand, "work-item-card");
      assert.equal(cards.length, Math.min(count, 8) + 1);
      assert.equal(cards.at(-1), links[0]);
      const empty = byClass(doneBand, "work-band-empty");
      assert.equal(empty.length, count === 0 ? 1 : 0);
      if (!count) assert.equal(empty[0].textContent, "Nothing finished in the last 24 hours.");
      assert.equal(byClass(byClass(root, "work-band-release")[0], "see-more-card").length, 0);
    });
  }
}
