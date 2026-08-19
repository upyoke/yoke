import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import { frontierClient } from "./universe_ui_frontier_view_test_support.mjs";

test("Frontier shows the ready ranking and one blocked row per gate point", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  const client = frontierClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // One read serves both panels, scoped to the selected project.
  assert.deepEqual(
    client.requests.filter((request) => request.function === "frontier.list"),
    [{ function: "frontier.list", payload: { project: "1" } }],
  );
  assert.deepEqual(
    client.requests.filter((request) => request.function === "sessions.list"),
    [
      {
        function: "sessions.list",
        payload: { project: "1", liveness: "active", limit: 500 },
      },
      {
        function: "sessions.list",
        payload: { project: "1", liveness: "stale", limit: 500 },
      },
    ],
  );

  // The ready table follows the prototype's steering anatomy: ordinal,
  // item, workflow, project, structural progress, why, then the command.
  // Project stays visible even under one selected scope so the row remains
  // self-identifying when copied or scanned.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells.slice(0, 7), [
    "1", "ship it", "issue", "🐄 yoke", "",
    "No unsatisfied activation gates; unclaimed.", "yoke advance YOK-7",
  ]);
  assert.deepEqual(cells.slice(7), [
    "waits YOK-8", "🐄 yoke", "YOK-7", "YOK-7 not done", "activation",
    "waits YOK-9", "🐄 yoke", "PLT-70", "lands after PLT-70", "integration",
    "waits YOK-10", "🐄 yoke", "YOK-7", "closes after YOK-7", "closure",
  ]);
  assert.deepEqual(
    byClass(root, "frontier-item-ref").map((node) => node.textContent),
    ["YOK-7", "YOK-8", "YOK-9", "YOK-10"],
  );
  assert.equal(byClass(root, "stage-progress").length, 1);
  assert.equal(byClass(root, "stage-progress-segment").length, 10);
  assert.equal(
    byClass(root, "stage-progress-segment")
      .filter((node) => node.classList.contains("is-complete")).length,
    5,
  );
  assert.deepEqual(
    byClass(root, "stage-progress-label").map((node) => node.textContent),
    ["5/10"],
  );
  assert.equal(byClass(root, "workflow-badge").length, 1);
  assert.equal(byClass(root, "workflow-badge")[0].textContent, "issue");
  assert.equal(byClass(root, "metric-strip").length, 1);
  assert.deepEqual(
    byClass(root, "metric").map((node) => [
      node.children[0].textContent,
      node.children[1].textContent,
    ]),
    [
      ["1", "ready now"],
      ["1", "in progress"],
      ["3", "blocked"],
      ["0", "waiting on you"],
    ],
  );
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "", "item", "Type", "project", "progress",
      "why it is ready", "run in your harness",
      "item", "project", "waiting on", "why", "gate",
    ],
  );
  assert.deepEqual(
    byClass(root, "frontier-panel-detail").map((node) => node.textContent),
    ["scoped to yoke", "why these cannot run yet"],
  );
  assert.deepEqual(
    byClass(root, "frontier-session-count").map((node) => node.textContent),
    ["· 1 session"],
  );
  assert.equal(byClass(root, "raw-toggle").length, 0);
  assert.deepEqual(
    byClass(root, "panel-count").map((node) => node.textContent),
    ["· ranked", "· 3"],
  );

  // The item cell links to the items drill-in with the bare numeric ref —
  // frontier rows point at items, never at a frontier drill-in.
  assert.deepEqual(
    byClass(root, "row-link").map((node) => node.href),
    [
      "#/items/7?project=1",
      "#/items/8?project=1", "#/items/7?project=1",
      "#/items/9?project=1", "#/items/70?project=2",
      "#/items/10?project=1", "#/items/7?project=1",
    ],
  );

  // The run command is a code element carrying the exact copyable text,
  // never a button; the blocked "waiting on" refs render mono the same way.
  const codeNodes = allNodes(root).filter((node) => node.tagName === "CODE");
  assert.deepEqual(
    codeNodes.map((node) => node.textContent),
    ["yoke advance YOK-7"],
  );
  assert.equal(
    allNodes(root).filter(
      (node) => node.tagName === "BUTTON" &&
        node.textContent.includes("yoke advance"),
    ).length,
    0,
  );

  // Gate pills color by severity of what the gate withholds: activation
  // blocks a start (crit), integration only orders the landing (warn),
  // closure merely holds the closeout (idle).
  const gatePills = allNodes(root).filter(
    (node) => node.classList && node.classList.contains("pill") &&
      ["activation", "integration", "closure"]
        .includes(node.textContent),
  );
  assert.deepEqual(
    gatePills.map((pill) => [pill.textContent, pill.className]),
    [
      ["activation", "pill crit"],
      ["integration", "pill warn"],
      ["closure", "pill idle"],
    ],
  );
  mounted.unmount();
});

test("an empty frontier states both halves honestly", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{
                id: 1, slug: "yoke", name: "Yoke", emoji: "🐄",
              }],
            },
          },
        };
      }
      if (request.function === "frontier.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              ready_rows: [], blocked_rows: [],
              frozen_count: 0, wip_cap: 5, wip_active: 0,
            },
          },
        };
      }
      if (request.function === "sessions.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: [] },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // The "all" default is one unfiltered read.
  assert.ok(requests.some(
    (request) => request.function === "frontier.list" &&
      !("project" in request.payload),
  ));
  const empties = byClass(root, "empty").map((node) => node.textContent);
  assert.deepEqual(empties, [
    "No ready work in this scope.",
    "Nothing blocked in this scope.",
  ]);
  assert.equal(byClass(root, "frontier-table").length, 2);
  assert.deepEqual(
    byClass(root, "frontier-empty").map(
      (node) => node.attributes.get("colspan"),
    ),
    ["7", "5"],
  );
  assert.deepEqual(
    byClass(root, "frontier-panel-detail").map((node) => node.textContent),
    ["across all projects", "why these cannot run yet"],
  );
  assert.deepEqual(
    byClass(root, "frontier-session-count").map((node) => node.textContent),
    ["· 0 sessions"],
  );
  assert.equal(byClass(root, "raw-toggle").length, 0);
  mounted.unmount();
});

test("a failed Frontier read keeps both facets honest", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return {
          status: 200,
          envelope: { success: true, result: { name: "Yoke" } },
        };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{
                id: 1, slug: "yoke", name: "Yoke", emoji: "🐄",
              }],
            },
          },
        };
      }
      if (request.function === "frontier.list") {
        return {
          status: 503,
          envelope: {
            success: false,
            error: { message: "scheduler unavailable" },
          },
        };
      }
      if (request.function === "sessions.list") {
        return {
          status: 200,
          envelope: { success: true, result: { rows: [] } },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    byClass(root, "error").map((node) => node.textContent),
    [
      "read failed (HTTP 503): scheduler unavailable",
      "read failed (HTTP 503): scheduler unavailable",
    ],
  );
  assert.equal(byClass(root, "metric-strip").length, 0);
  assert.equal(byClass(root, "frontier-table").length, 0);
  mounted.unmount();
});

test("Frontier keeps the prototype table geometry", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_secondary_views.css",
    import.meta.url,
  ), "utf8");

  assert.match(css, /\.stage-progress\s*\{\s*display:\s*inline;/);
  assert.match(
    css,
    /\.frontier-ready-panel \.frontier-table\s*\{\s*min-width:\s*100%;/,
  );
  assert.match(
    css,
    /\.frontier-ready-panel \.frontier-table th:nth-child\(5\)\s*\{\s*width:\s*96px;/,
  );
  assert.doesNotMatch(
    css,
    /\.frontier-project\s*\{[^}]*white-space:\s*nowrap;/,
  );
});
