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

test("the actor chip names the viewer, and is absent when nobody does", async (t) => {
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

  assert.deepEqual(mountWith({ id: 2, kind: "human", label: "Ben" }), ["Ben"]);
  assert.deepEqual(mountWith({ id: 2, kind: "human" }), ["actor 2"]);
  assert.deepEqual(
    mountWith({ id: 3, kind: "system", systemComponent: "skill-simulate" }),
    ["actor 3", "skill-simulate"],
  );
  assert.equal(mountWith(null), null);
});

test("an epic's detail carries its tasks; an issue's does not", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const drillInto = async (workflowId) => {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/items/7?project=1";
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
        if (request.function === "items.get.run") {
          return {
            status: 200,
            envelope: {
              success: true,
              result: {
                item_id: 7,
                fields: {
                  id: "7", workflow_id: workflowId, workflow_version_id: "1", status: "planned", title: "t", body: "# Spec",
                },
              },
            },
          };
        }
        if (request.function === "epic_tasks.list.run") {
          return {
            status: 200,
            envelope: {
              success: true,
              result: {
                epic_id: 7,
                tasks: [{ task_num: 1, title: "first", status: "done" }],
              },
            },
          };
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    };
    const mounted = mountUniverseApp(root, { client });
    await settle();
    const text = allNodes(root).map((node) => node.textContent || "").join(" ");
    const detailRequest = requests.find(
      (request) => request.function === "items.get.run",
    );
    const tasksRequest = requests.find(
      (request) => request.function === "epic_tasks.list.run",
    );
    const result = {
      askedForTasks: tasksRequest !== undefined,
      target: detailRequest.target,
      tasksTarget: tasksRequest ? tasksRequest.target : null,
      tasksPayload: tasksRequest ? tasksRequest.payload : null,
      showsTask: text.includes("first"),
      breadcrumbs: byClass(root, "breadcrumb").length,
      pageHeads: byClass(root, "page-head").length,
    };
    mounted.unmount();
    return result;
  };

  const epic = await drillInto("epic");
  assert.deepEqual(epic.target, {
    kind: "item", item_ref: "7", project_id: "1",
  });
  assert.equal(epic.askedForTasks, true);
  // The tasks read resolves its epic through the target — the handler
  // refuses a call without target.epic_id.
  assert.deepEqual(epic.tasksTarget, {
    kind: "epic_task", epic_id: 7, project_id: "1",
  });
  assert.deepEqual(epic.tasksPayload, {});
  assert.equal(epic.showsTask, true);
  // The breadcrumb is a drill-in's whole head — no page head beside it.
  assert.equal(epic.breadcrumbs, 1);
  assert.equal(epic.pageHeads, 0);

  const issue = await drillInto("issue");
  assert.equal(issue.askedForTasks, false);
});

test("an unblocked item reports no blocking reason", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  let itemsRequest = null;
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] } } };
      }
      if (request.function === "items.list.run") {
        itemsRequest = request;
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                { id: 1, title: "runs", workflow_id: "issue", workflow_version_id: 1, status: "idea", priority: "medium", blocked: "0", blocked_reason: "", project: "yoke" },
                { id: 2, title: "waits", workflow_id: "epic", workflow_version_id: 1, status: "idea", priority: "high", blocked: "1", blocked_reason: "upstream schema", project: "yoke" },
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

  // The "all" default reads unfiltered and labels each row's project.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "1", "yoke", "issue", "1", "runs", "idea", "medium", "",
    "2", "yoke", "epic", "1", "waits", "idea", "high", "upstream schema",
  ]);
  // The drill-in carries the row's own project id, mapped from its slug.
  const rowLinks = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("row-link"))
    .map((node) => node.href);
  assert.deepEqual(rowLinks, ["#/items/1?project=1", "#/items/2?project=1"]);
  assert.ok(["workflow_id", "workflow_version_id"].every((field) => itemsRequest.payload.fields.includes(field)));
  assert.ok(itemsRequest.payload.fields.includes("blocked_reason"));
  assert.ok(itemsRequest.payload.fields.includes("project"));
  assert.ok(!("project" in itemsRequest.payload));
  // A read that served no total earns no header count — rows.length never
  // stands in for the engine's number.
  assert.equal(byClass(root, "panel-count").length, 0);
  mounted.unmount();
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
                { timestamp: "now", category: "observation", agent: "tester", context: "open", reviewed_at: null },
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
    "now", "observation", "tester", "open", "",
    "then", "failed", "doctor", "closed", "later",
  ]);
  mounted.unmount();
});
