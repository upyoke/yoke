import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  relativeAge,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";

test("strategy rows render the prototype corpus facts", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
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
      if (request.function === "strategy.surface.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              docs: [
                {
                  slug: "MISSION", title: "Mission statement",
                  updated_at: "2026-07-01", updated_by: "ben",
                  parent_slug: null, revisions: 4,
                  execution_state: "available", archived: false,
                },
                {
                  slug: "VISION", title: "Vision",
                  updated_at: "2026-06-30", updated_by: null,
                  parent_slug: "MISSION", revisions: 2,
                  execution_state: "available", archived: true,
                },
              ],
              writes: [],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // At the "all" default the docs read fans out per project, and each row
  // wears the slug of the project bucket that requested it. An unresolved
  // editor remains empty and the hierarchy is visible in the purpose cell.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TH" || node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "Doc", "project", "Purpose / ancestry", "Last editor", "Last write",
    "Revisions", "Execution",
    "MISSION", "yoke", "Mission statement", "b",
    relativeAge("2026-07-01"), "4", "available",
    "VISION", "yoke", "Vision", "",
    relativeAge("2026-06-30"), "2", "archived",
  ]);
  assert.ok(requests.some(
    (request) => request.function === "strategy.surface.list",
  ));
  mounted.unmount();
});
