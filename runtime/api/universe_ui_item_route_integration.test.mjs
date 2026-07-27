import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { detailItem } from "./universe_ui_items_test_support.mjs";

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
              result: { rows: [{ id: 1, name: "Yoke" }] },
            },
          };
        }
        if (request.function === "items.detail.get") {
          return {
            status: 200,
            envelope: {
              success: true,
              result: {
                item: {
                  ...detailItem(workflowId),
                  id: 7,
                  public_ref: "7",
                  project: { id: 1, slug: "yoke", name: "Yoke" },
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
    const text = allNodes(root).map(
      (node) => node.textContent || "",
    ).join(" ");
    const detailRequest = requests.find(
      (request) => request.function === "items.detail.get",
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
  assert.deepEqual(epic.tasksTarget, {
    kind: "epic_task", epic_id: 7, project_id: "1",
  });
  assert.deepEqual(epic.tasksPayload, {});
  assert.equal(epic.showsTask, true);
  assert.equal(epic.breadcrumbs, 1);
  assert.equal(epic.pageHeads, 1);

  const issue = await drillInto("issue");
  assert.equal(issue.askedForTasks, false);
});

test("Items roster names projects but keeps blocking details out", async (t) => {
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
              rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
            },
          },
        };
      }
      if (request.function === "items.overview.list") {
        itemsRequest = request;
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                {
                  id: 1, public_ref: "YOK-1", project_id: 1,
                  title: "runs", workflow_id: "issue",
                  workflow_version_id: 1, status: "idea",
                  stage_label: "Idea", owner: "", claimed_by: null,
                  blocked: false, blocked_reason: "",
                },
                {
                  id: 2, public_ref: "YOK-2", project_id: 1,
                  title: "waits", workflow_id: "epic",
                  workflow_version_id: 1, status: "idea",
                  stage_label: "Idea", owner: "", claimed_by: null,
                  blocked: true, blocked_reason: "upstream schema",
                },
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
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "YOK-1", "yoke", "runs", "issue", "Idea", "unassigned", "—",
    "YOK-2", "yoke", "waits", "epic", "Idea", "unassigned", "—",
  ]);
  assert.ok(!allNodes(root).some(
    (node) => node.textContent === "upstream schema",
  ));
  assert.deepEqual(
    byClass(root, "row-link").map((node) => node.href),
    ["#/items/YOK-1?project=1", "#/items/YOK-2?project=1"],
  );
  assert.deepEqual(itemsRequest.payload, {});
  assert.equal(byClass(root, "panel-count").length, 0);
  mounted.unmount();
});
