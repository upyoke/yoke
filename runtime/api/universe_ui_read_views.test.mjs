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

test("the actor chip renders avatar, name, and authoritative actor id", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const mountWith = (currentActor) => {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    const mounted = mountUniverseApp(root, {
      client: injectedClient(),
      ...(currentActor ? { currentActor } : {}),
    });
    const chip = allNodes(root).find(
      (node) => node.classList && node.classList.contains("actor-chip"),
    );
    const text = chip
      ? allNodes(chip).map((node) => node.textContent || "").filter(Boolean)
      : null;
    mounted.unmount();
    return text;
  };

  assert.deepEqual(
    mountWith({ id: 2, kind: "human", label: "Ben" }),
    ["B", "Ben", "actor 2"],
  );
  assert.deepEqual(
    mountWith({ id: 2, kind: "human" }),
    ["a", "actor 2", "actor 2"],
  );
  assert.deepEqual(
    mountWith({ id: 3, kind: "system", systemComponent: "skill-simulate" }),
    ["⚙", "actor 3", "actor 3"],
  );
  assert.deepEqual(mountWith(null), ["l", "local actor"]);
});

// The events and ouroboros reads are project-scoped in the engine and refuse
// a call that names no project — an unfiltered one comes back denied, not
// empty. So "all" must ask per roster project rather than once with nothing.
for (const [view, functionId] of [
  ["events", "events.query.run"],
  ["ouroboros", "ouroboros.entry.list"],
]) {
  test(`${view} at "all" asks per project, never a projectless read`, async (t) => {
    const originalFetch = globalThis.fetch;
    t.after(() => { globalThis.fetch = originalFetch; });
    globalThis.fetch = () => response(200, {});
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = `#/${view}`;
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
                rows: [
                  { id: 1, slug: "alpha", name: "Alpha" },
                  { id: 2, slug: "beta", name: "Beta" },
                ],
              },
            },
          };
        }
        if (request.function === functionId) {
          // The engine denies a project-scoped read that names no project;
          // answering rows here would hide the very shape under test.
          if (!request.payload.project) {
            return {
              status: 403,
              envelope: {
                success: false,
                error: {
                  message:
                    "could not resolve a target project for project-scoped function",
                },
              },
            };
          }
          return {
            status: 200,
            envelope: { success: true, result: { rows: [], entries: [] } },
          };
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    };

    const mounted = mountUniverseApp(root, { client });
    await settle();

    assert.deepEqual(
      requests.filter((request) => request.function === functionId)
        .map((request) => request.payload.project),
      ["1", "2"],
    );
    // The denial never reaches the panel, because no projectless call is made.
    assert.equal(byClass(root, "error").length, 0);
    mounted.unmount();
  });
}

test("Ouroboros reads observations and keeps review state visible", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/ouroboros?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "ouroboros.entry.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              entries: [
                {
                  id: 22,
                  timestamp: "now",
                  category: "field-note-observation",
                  agent: "tester",
                  context: "open",
                  reviewed_at: null,
                  promoted_dash: {
                    item_ref: "YOK-90",
                    item_id: 90,
                    project_id: 1,
                  },
                },
                { timestamp: "then", category: "failed", agent: "doctor", context: "closed", reviewed_at: "later" },
              ],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    requests.find((request) => request.function === "ouroboros.entry.list"),
    { function: "ouroboros.entry.list", payload: { project: "1" } },
  );
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "now", "field-note-observation", "tester", "open", "", "YOK-90",
    "then", "failed", "doctor", "closed", "later", "",
  ]);
  assert.equal(
    byClass(root, "row-link").find((node) => node.textContent === "YOK-90").href,
    "#/items/90?project=1",
  );
  mounted.unmount();
});

test("Ouroboros field-note drill-in keeps its promoted Dash reachable", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/ouroboros/22?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
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
            result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] },
          },
        };
      }
      if (request.function === "ouroboros.entry.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              entry: {
                id: 22,
                category: "field-note-observation",
                agent: "tester",
                context: "curate",
                body: "Turn this observation into focused work.",
                promoted_dash: {
                  item_ref: "YOK-90",
                  item_id: 90,
                  project_id: 1,
                },
              },
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    requests.find((request) => request.function === "ouroboros.entry.get"),
    {
      function: "ouroboros.entry.get",
      payload: { entry_id: 22, project: "1" },
    },
  );
  assert.match(
    allNodes(root).map((node) => node.textContent || "").join(" "),
    /Turn this observation into focused work\./,
  );
  assert.equal(
    byClass(root, "item-action")[0].href,
    "#/items/90?project=1",
  );
  mounted.unmount();
});
