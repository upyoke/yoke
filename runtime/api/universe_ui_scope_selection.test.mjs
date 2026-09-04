import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  createScopePicker,
  navEntry,
  scopeForEntry,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

// A two-project universe whose items are distinguishable per project, for
import {
  itemsCalls, scopeChips, twoProjectClient,
} from "./universe_ui_read_views_test_support.mjs";

test("a multi view defaults to the whole universe: All chip on, unfiltered read", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();

  const chips = scopeChips(root);
  assert.deepEqual(
    chips.map((chip) => chip.textContent), ["All", "ALP", "BET"],
  );
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")),
    [true, false, false],
  );
  assert.equal(byClass(root, "scope-label")[0].textContent, "Projects");
  // "all" is one unfiltered call, and the default writes no query param.
  assert.deepEqual(
    itemsCalls(client).map((request) => request.payload.project), [undefined],
  );
  assert.equal(documentNode.defaultView.location.hash, "#/items");
  mounted.unmount();
});

test("chips narrow to one, widen to a pair, and empty back out to All", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const click = async (label) => {
    const before = client.requests.length;
    scopeChips(root).find((chip) => chip.textContent === label)
      .dispatchEvent(new Event("click"));
    await settle();
    return client.requests.slice(before)
      .filter((request) => request.function === "items.overview.list");
  };

  // One project: the read carries it and the hash names it.
  const narrowed = await click("ALP");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=1");
  assert.deepEqual(narrowed.map((request) => request.payload.project), ["1"]);
  assert.deepEqual(
    scopeChips(root).map((chip) => chip.classList.contains("on")),
    [false, true, false],
  );
  // Exactly one project needs no project column.
  assert.ok(!allNodes(root).some(
    (node) => node.tagName === "TH" && node.textContent === "project",
  ));

  // A second chip widens to the pair: one read per member, rows merged in
  // call order, with each row retaining its own project for drill-in.
  const paired = await click("BET");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=1,2");
  assert.deepEqual(paired.map((request) => request.payload.project), ["1", "2"]);
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "YOK-11", "alpha", "alpha item", "issue", "Idea", "unassigned", "—",
    "YOK-21", "beta", "beta item", "issue", "Idea", "unassigned", "—",
  ]);
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["ID", "project", "Title", "Workflow", "Status", "Owner", "Claimed by"],
  );
  // Each row's drill-in carries that row's own project.
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.classList && node.classList.contains("row-link"))
      .map((node) => node.href),
    ["#/items/11?project=1", "#/items/21?project=2"],
  );

  // Removing members one at a time: the last removal returns to "all",
  // whose read omits the project filter and whose route has no query.
  await click("ALP");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=2");
  const widened = await click("BET");
  assert.equal(documentNode.defaultView.location.hash, "#/items");
  assert.deepEqual(widened.map((request) => request.payload.project), [undefined]);
  assert.deepEqual(
    scopeChips(root).map((chip) => chip.classList.contains("on")),
    [true, false, false],
  );
  mounted.unmount();
});

test("strategy at All fans out one call per roster project", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    client.requests
      .filter((request) => request.function === "strategy.surface.list")
      .map((request) => request.target),
    [
      { kind: "global", project_id: "1" },
      { kind: "global", project_id: "2" },
    ],
  );
  // Rows from every bucket render with their owning project.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "PLAN-1", "alpha", "plan", "b", "today", "1", "available",
    "PLAN-2", "beta", "plan", "b", "today", "1", "available",
  ]);
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "Doc", "project", "Purpose / ancestry", "Last editor", "Last write",
      "Revisions", "Execution",
    ],
  );
  assert.deepEqual(
    byClass(root, "strategy-doc-ancestry").map((node) => node.textContent),
    ["top-level strategy", "top-level strategy"],
  );
  assert.deepEqual(
    byClass(root, "strategy-editor-name").map((node) => node.textContent),
    ["ben", "ben"],
  );
  // Each doc row opens its own drill-in, carrying the bucket's project.
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.classList && node.classList.contains("row-link"))
      .map((node) => node.href),
    ["#/strategy/PLAN-1?project=1", "#/strategy/PLAN-2?project=2"],
  );
  // The panel keeps the prototype's scope label instead of inventing a count.
  assert.equal(
    byClass(root, "panel-count")[0].textContent,
    "· across all projects",
  );
  mounted.unmount();
});

test("each screen remembers its own scope across nav round trips", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/items?project=2";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const navigate = async (hash) => {
    windowNode.location.hash = hash;
    windowNode.dispatchEvent(new Event("hashchange"));
    await settle();
  };

  await navigate("#/events");
  const itemsLink = byClass(root, "nav-link").find((link) =>
    allNodes(link).some(
      (node) => node.classList.contains("txt") &&
        node.textContent === "Items",
    ));
  // The nav link back carries the scope the screen last held...
  assert.equal(itemsLink.href, "#/items?project=2");

  // ...and following it restores that scope's read.
  await navigate(itemsLink.href);
  const lastItems = itemsCalls(client).at(-1);
  assert.equal(lastItems.payload.project, "2");
  mounted.unmount();
});

test("an explicit QA Activity All route overrides its remembered project scope", () => {
  const projects = [
    { id: "buzz", slug: "buzz", name: "Buzz" },
    { id: "yoke", slug: "yoke", name: "Yoke" },
  ];
  const selections = new Map();
  const entry = navEntry("qa-activity");

  assert.deepEqual(
    scopeForEntry(entry, "buzz", projects, selections),
    ["buzz"],
  );
  const route = parseUniverseRoute("#/qa-activity?project=all");
  assert.equal(route.view, "qa-activity");
  assert.equal(route.project, "all");
  assert.equal(
    scopeForEntry(entry, route.project, projects, selections),
    "all",
  );
  assert.equal(selections.get("qa-activity"), "all");
});

test("a single-scope picker offers radio chips and no All chip", () => {
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  const selections = new Map();
  const rendered = [];
  const bar = createScopePicker({
    documentNode,
    entry: navEntry("github"),
    scope: "1",
    projects: [
      { id: 1, slug: "alpha", name: "Alpha", public_item_prefix: "ALP" },
      { id: 2, slug: "beta", name: "Beta", public_item_prefix: "BET" },
    ],
    renderRoute: () => rendered.push(true),
    scopeSelections: selections,
    segment: null,
    windowNode,
  });

  assert.equal(byClass(bar, "scope-label")[0].textContent, "Project");
  const chips = byClass(bar, "scope-chip");
  assert.deepEqual(chips.map((chip) => chip.textContent), ["ALP", "BET"]);
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")), [true, false],
  );

  // Radio semantics: a click selects exactly that project.
  chips[1].dispatchEvent(new Event("click"));
  assert.equal(selections.get("github"), "2");
  assert.equal(windowNode.location.hash, "#/github?project=2");
  assert.equal(rendered.length, 1);
});

test("a multi view still reads an empty universe, unfiltered", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      if (request.function === "items.overview.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: [], count: 0 },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  // An unfiltered read over an empty universe is honest: the view renders
  // its own empty table rather than a "no projects" panel.
  assert.ok(requests.some(
    (request) => request.function === "items.overview.list" &&
      !("project" in request.payload),
  ));
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("No items match this view."));
  assert.ok(!text.includes("no projects yet"));
  mounted.unmount();
});
