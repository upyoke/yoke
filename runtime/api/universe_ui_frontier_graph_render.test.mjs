// The Waiting graph as the page draws it: tiles, edge paths, fan-out stacks,
// selection and the detail panel, and the Frontier page's Waiting and On hold
// bands from a served frontier.list.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { frontierGraphSection } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_graph.js";
import { DEPENDENCY_GRAPH_FLOOR_MESSAGE } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_frontier_bands.js";
import {
  FakeDocument,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { descendantText, recentIso, workbenchClient } from "./universe_ui_workbench_test_support.mjs";
import { state, stateModel } from "./frontier_dependency_states.mjs";

function draw(id) {
  const documentNode = new FakeDocument();
  const model = stateModel(state(id));
  const section = frontierGraphSection(documentNode, model, {
    claimantFor: () => null,
    cardFor: (ref) => {
      const card = documentNode.createElement("article");
      card.className = "work-item-card";
      card.textContent = `card ${ref}`;
      return model.nodes.get(ref).band === "off" ? null : card;
    },
  });
  const grid = byClass(section, "fdv-graph-grid")[0];
  const tile = (ref) => byClass(grid, "fdv-tile").find(
    (node) => node.getAttribute("data-fdv-ref") === ref,
  );
  return { section, grid, tile, model };
}

test("tiles carry the item link, stage, leverage, title, gate and rationale", () => {
  const { section, tile } = draw("today");
  assert.deepEqual(
    byClass(section, "fdv-graph-col-head").map(ownTextContent),
    ["Holding work up", "1 step behind", "2 steps behind", "3 steps behind", "4 steps behind"],
  );
  const root = tile("YOK-3717");
  assert.equal(root.getAttribute("role"), "button");
  assert.equal(root.tabIndex, 0);
  assert.equal(root.getAttribute("data-band"), "active");
  assert.equal(byClass(root, "fdv-tile-ref")[0].href, "/items/YOK-3717");
  assert.equal(ownTextContent(byClass(root, "fdv-unblocks")[0]), "unblocks 7");
  assert.equal(ownTextContent(byClass(root, "fdv-tile-title")[0]), "Rename execution lanes to levels");
  const dependent = tile("YOK-3725");
  assert.equal(ownTextContent(byClass(dependent, "fdv-tile-meta")[0]), "Starts after YOK-3717 merges");
  assert.match(dependent.title, /^YOK-3717: The lanes-to-levels rename/);
});

test("one path per edge, and only the longest chain is heavier", () => {
  const { section } = draw("today");
  const paths = byClass(section, "fdv-edge");
  assert.equal(paths.length, 9);
  assert.deepEqual(
    paths.filter((path) => path.classList.contains("is-critical"))
      .map((path) => `${path.getAttribute("data-from")}>${path.getAttribute("data-to")}`),
    ["YOK-3720>YOK-3721", "YOK-3719>YOK-3720", "YOK-3718>YOK-3719", "YOK-3717>YOK-3718"],
  );
});

test("stuck and deadlocked tiles are marked on the tiles themselves", () => {
  const { section, tile } = draw("stuck");
  assert.ok(tile("YOK-3830").classList.contains("is-stall"));
  assert.ok(tile("YOK-3831").classList.contains("is-stuck"));
  assert.ok(tile("YOK-3840").classList.contains("is-dead"));
  assert.ok(tile("BUZ-90").classList.contains("is-ghost") === false);
  const divider = byClass(section, "fdv-graph-divider")[0];
  assert.equal(ownTextContent(divider), "Deadlocked");
  assert.ok(divider.classList.contains("is-stuck"));
  assert.equal(ownTextContent(byClass(tile("YOK-3860"), "fdv-tile-meta")[0]),
    "Deadlock — YOK-3861 ⇄ YOK-3860 wait on each other");
});

test("a fan-out stack expands in place", () => {
  const { section, grid } = draw("wide");
  const stack = byClass(grid, "fdv-stack")[0];
  assert.equal(descendantText(stack), "+9 moreStarts after YOK-3900 merges");
  const folded = byClass(grid, "fdv-stack-items")[0];
  assert.equal(folded.hidden, true);
  assert.equal(byClass(folded, "fdv-tile").length, 9);
  stack.dispatchEvent(new Event("click"));
  assert.equal(folded.hidden, false);
  assert.equal(byClass(section, "fdv-stack").length, 0);
});

test("hover lights a lineage; a click pins it and opens the detail panel", () => {
  const { section, tile } = draw("today");
  tile("YOK-3758").dispatchEvent(new Event("pointerenter"));
  assert.ok(section.classList.contains("has-focus"));
  assert.ok(tile("YOK-3757").classList.contains("is-lit"));
  assert.equal(tile("YOK-3717").classList.contains("is-lit"), false);

  tile("YOK-3718").dispatchEvent(new Event("click"));
  const layout = byClass(section, "fdv-graph-layout")[0];
  assert.ok(layout.classList.contains("has-detail"));
  assert.ok(tile("YOK-3718").classList.contains("is-selected"));
  const detail = byClass(section, "fdv-graph-detail")[0];
  assert.deepEqual(byClass(detail, "fdv-detail-h").map(ownTextContent), ["Waiting on 1", "Holding back 3"]);
  const up = byClass(detail, "fdv-detail-list")[0].children[0];
  assert.equal(ownTextContent(byClass(up, "fdv-gate")[0]), "blocks start");
  assert.equal(ownTextContent(byClass(up, "fdv-detail-copy")[0]), "until it merges · now implementing");
  assert.equal(ownTextContent(byClass(up, "fdv-detail-why")[0]),
    "Universe level storage builds on the renamed level columns and settings keys");
  assert.equal(ownTextContent(byClass(detail, "work-item-card")[0]), "card YOK-3718");

  // A row traces its item; Close unpins and the graph returns to full width.
  up.dispatchEvent(new Event("click"));
  assert.ok(tile("YOK-3717").classList.contains("is-selected"));
  byClass(detail, "fdv-lane-jump")[0].dispatchEvent(new Event("click"));
  assert.equal(layout.classList.contains("has-detail"), false);
  assert.equal(detail.children.length, 0);
});

test("Enter on a focused tile selects it", () => {
  const { section, tile } = draw("gates");
  const target = tile("YOK-3823");
  const event = Object.assign(new Event("keydown"), { key: "Enter" });
  Object.defineProperty(event, "target", { value: target });
  target.dispatchEvent(event);
  const detail = byClass(section, "fdv-graph-detail")[0];
  assert.equal(ownTextContent(byClass(detail, "fdv-gate")[0]), "blocks close");
  assert.equal(ownTextContent(byClass(detail, "fdv-detail-copy")[0]),
    "until it is live on prod · now release · stage ✓ · prod not yet");
});

test("the phone outline lists each chain once from its root", () => {
  const { section } = draw("today");
  const outline = byClass(section, "fdv-graph-outline")[0];
  const roots = byClass(outline, "fdv-outline").map(
    (tree) => tree.children[0].children[0].getAttribute("data-fdv-ref"),
  );
  assert.deepEqual(roots, ["YOK-3717", "YOK-3757"]);
  assert.equal(byClass(outline, "fdv-tile").length, 11);
});

function row(ref, projectId, facts = {}) {
  const sequence = Number(ref.split("-").at(-1));
  return {
    public_ref: ref, title: `${ref} work`,
    project: projectId === 1 ? "yoke" : "beta", project_id: projectId,
    project_sequence: sequence, workflow_id: "issue", status: "idea",
    created_at: recentIso(12), updated_at: recentIso(1),
    terminal: false, finished: false, finished_at: null, ...facts,
  };
}

function edge(blocker, dependent, facts = {}) {
  return {
    blocking_item: blocker, dependent_item: dependent, gate_point: "activation",
    satisfaction: "fact:merged", rationale: `${dependent} needs ${blocker}`,
    blocking_stage: "idea", blocking_terminal: false, blocking_abandoned: false, blocking_title: "",
    blocking_project_id: 1, blocking_project_sequence: Number(blocker.split("-")[1]),
    dependent_project_id: 1, dependent_project_sequence: Number(dependent.split("-")[1]),
    environment: null, ...facts,
  };
}

async function mount(t, hash, frontier) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = hash;
  const root = documentNode.createElement("div");
  const items = [
    row("YOK-7", 1, { frozen: true, blocked_reason: "Waiting for a product decision." }),
    row("YOK-12", 1),
    row("BET-3", 2),
  ];
  const mounted = mountUniverseApp(root, { client: workbenchClient({
    "items.overview.list": { rows: items },
    "frontier.list": frontier,
  }) });
  t.after(() => mounted.unmount());
  await settle();
  const band = (key) => byClass(root, `work-band-${key}`)[0];
  return { band, count: (key) => byClass(band(key), "work-band-count")[0].textContent };
}

const waitingOnFrozen = {
  ready_rows: [],
  blocked_rows: [
    { public_ref: "YOK-12", project_id: 1, project: "yoke", blocking_item: "YOK-7", why: "x" },
    { public_ref: "BET-3", project_id: 2, project: "beta", blocking_item: "YOK-12", why: "y" },
  ],
  dependency_edges: [
    edge("YOK-7", "YOK-12"),
    edge("YOK-12", "BET-3", { dependent_project_id: 2 }),
  ],
};

test("a frozen item others wait on stalls the graph rather than sitting On hold", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=1", waitingOnFrozen);
  assert.equal(count("waiting"), "3");
  assert.equal(count("hold"), "0");
  assert.equal(ownTextContent(byClass(band("hold"), "work-band-empty")[0]), "Nothing is on hold.");
  const frozen = byClass(band("waiting"), "fdv-tile").find(
    (node) => node.getAttribute("data-fdv-ref") === "YOK-7",
  );
  assert.ok(frozen.classList.contains("is-stall"));
  assert.equal(ownTextContent(byClass(frozen, "fdv-tile-meta")[0]),
    "Frozen — Waiting for a product decision.");
});

test("the project filter keeps a chain that crosses into the selected project", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=2", waitingOnFrozen);
  // Beta's item waits on Yoke work, so that Yoke work stays in view.
  assert.equal(count("waiting"), "3");
  assert.deepEqual(
    byClass(byClass(band("waiting"), "fdv-graph-grid")[0], "fdv-tile")
      .map((node) => node.getAttribute("data-fdv-ref")),
    ["YOK-7", "YOK-12", "BET-3"],
  );
});

test("with nothing waiting, Waiting says so and holds its count at zero", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=1", {
    ready_rows: [], blocked_rows: [], dependency_edges: [],
  });
  assert.equal(count("waiting"), "0");
  assert.equal(ownTextContent(byClass(band("waiting"), "work-band-empty")[0]),
    "Nothing is waiting on other work.");
  assert.equal(count("hold"), "1");
});

test("a serving build without dependency edges refuses the graph by its floor", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=1", {
    ready_rows: [], blocked_rows: [],
  });
  for (const key of ["waiting", "hold"]) {
    assert.equal(ownTextContent(byClass(band(key), "work-band-error")[0]), DEPENDENCY_GRAPH_FLOOR_MESSAGE);
    assert.equal(count(key), "");
  }
  assert.match(DEPENDENCY_GRAPH_FLOOR_MESSAGE, /Update that server/);
  assert.equal(byClass(band("waiting"), "fdv-tile").length, 0);
});

test("an item only its merge waits on stays Ready, with its edge in the graph", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=1", {
    ready_rows: [{ ...row("YOK-12", 1), public_ref: "YOK-12", why_ready: "ready" }],
    blocked_rows: [{
      public_ref: "YOK-12", project_id: 1, project: "yoke", blocking_item: "YOK-7",
      gate_point: "integration", why: "lands after",
    }],
    dependency_edges: [edge("YOK-7", "YOK-12", { gate_point: "integration" })],
  });
  assert.equal(count("ready"), "1");
  const tile = byClass(band("waiting"), "fdv-tile").find(
    (node) => node.getAttribute("data-fdv-ref") === "YOK-12",
  );
  assert.equal(tile.getAttribute("data-band"), "ready");
  assert.equal(ownTextContent(byClass(tile, "fdv-tile-meta")[0]), "Stuck upstream: YOK-7");
});

test("each repaint stops watching the canvas it replaced", async (t) => {
  const watched = [];
  const original = globalThis.ResizeObserver;
  t.after(() => { globalThis.ResizeObserver = original; });
  globalThis.ResizeObserver = class {
    constructor() { this.live = false; watched.push(this); }
    observe() { this.live = true; }
    disconnect() { this.live = false; }
  };
  // The first paint draws before delivery settles, the second after it.
  await mount(t, "/frontier?project=1", waitingOnFrozen);
  assert.ok(watched.length >= 2);
  assert.deepEqual(watched.map((observer) => observer.live).filter(Boolean), [true]);
});

test("a blocker that no longer resolves draws as a ghost its dependent waits on", async (t) => {
  const { band, count } = await mount(t, "/frontier?project=1", {
    ready_rows: [],
    blocked_rows: [{ public_ref: "YOK-12", project_id: 1, project: "yoke", blocking_item: "GONE-9", why: "z" }],
    dependency_edges: [edge("GONE-9", "YOK-12", {
      blocking_stage: null, blocking_title: null, blocking_project_id: null,
      blocking_project_sequence: null,
    })],
  });
  assert.equal(count("waiting"), "1");
  const ghost = byClass(band("waiting"), "fdv-tile").find(
    (node) => node.getAttribute("data-fdv-ref") === "GONE-9",
  );
  assert.ok(ghost.classList.contains("is-ghost"));
  assert.equal(ownTextContent(byClass(ghost, "fdv-tile-stage")[0]), "not on this Frontier");
});
