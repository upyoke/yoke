import assert from "node:assert/strict";
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

// A frontier universe with one ready step and one blocked row per gate
// point, so both panels and every gate pill family render from one read.
function frontierClient() {
  const requests = [];
  const blockedRow = (itemId, gatePoint, why) => ({
    item_id: itemId, title: `waits ${itemId}`, project: "yoke",
    blocking_item: "YOK-7", gate_point: gatePoint, why,
    satisfaction: "status:done",
  });
  return {
    requests,
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
            result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] },
          },
        };
      }
      if (request.function === "frontier.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              ready_rows: [{
                rank: 0, item_id: "YOK-7", title: "ship it",
                item_type: "issue", project: "yoke", status: "implementing",
                priority: "high", next_step: "advance",
                run_command: "yoke advance YOK-7",
                why_ready: "No unsatisfied activation gates; unclaimed.",
                unblocks_count: 3, downstream_depth: 1,
              }],
              blocked_rows: [
                blockedRow("YOK-8", "activation", "YOK-7 not done"),
                blockedRow("YOK-9", "integration", "lands after YOK-7"),
                blockedRow("YOK-10", "closure", "closes after YOK-7"),
              ],
              frozen_count: 0, wip_cap: 5, wip_active: 1,
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

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

  // Exactly one project: no project column in either table. The ready
  // table shows the engine's zero-based rank as an ordinal ("1" is the
  // top pick); the blocked table names the gate its row waits at,
  // verbatim.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "1", "YOK-7", "issue", "implementing", "high", "advance",
    "yoke advance YOK-7", "No unsatisfied activation gates; unclaimed.",
    "YOK-8", "YOK-7", "activation", "YOK-7 not done",
    "YOK-9", "YOK-7", "integration", "lands after YOK-7",
    "YOK-10", "YOK-7", "closure", "closes after YOK-7",
  ]);

  // The item cell links to the items drill-in with the bare numeric ref —
  // frontier rows point at items, never at a frontier drill-in.
  assert.deepEqual(
    byClass(root, "row-link").map((node) => node.href),
    ["#/items/7?project=1"],
  );

  // The run command is a code element carrying the exact copyable text,
  // never a button; the blocked "waiting on" refs render mono the same way.
  const codeNodes = allNodes(root).filter((node) => node.tagName === "CODE");
  assert.deepEqual(
    codeNodes.map((node) => node.textContent),
    ["yoke advance YOK-7", "YOK-7", "YOK-7", "YOK-7"],
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
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] } } };
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
  assert.deepEqual(empties, ["nothing ready to run", "nothing waiting"]);
  mounted.unmount();
});
