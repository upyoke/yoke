import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

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

  const drillInto = async (type) => {
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
                  id: "7", type, status: "planned", title: "t", body: "# Spec",
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
    const result = {
      askedForTasks: requests.some(
        (request) => request.function === "epic_tasks.list.run",
      ),
      target: detailRequest.target,
      showsTask: text.includes("first"),
    };
    mounted.unmount();
    return result;
  };

  const epic = await drillInto("epic");
  assert.deepEqual(epic.target, {
    kind: "item", item_ref: "7", project_id: "1",
  });
  assert.equal(epic.askedForTasks, true);
  assert.equal(epic.showsTask, true);

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
  let requestedFields = null;
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "items.list.run") {
        requestedFields = request.payload.fields;
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                { id: 1, title: "runs", type: "issue", status: "idea", priority: "medium", blocked: "0", blocked_reason: "" },
                { id: 2, title: "waits", type: "epic", status: "idea", priority: "high", blocked: "1", blocked_reason: "upstream schema" },
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

  const cellText = (node) => (
    node.textContent || (node.children[0] && node.children[0].textContent) || ""
  );
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "1", "issue", "runs", "idea", "medium", "",
    "2", "epic", "waits", "idea", "high", "upstream schema",
  ]);
  const rowLinks = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("row-link"))
    .map((node) => node.href);
  assert.deepEqual(rowLinks, ["#/items/1?project=1", "#/items/2?project=1"]);
  assert.ok(requestedFields.includes("type"));
  assert.ok(requestedFields.includes("blocked_reason"));
  mounted.unmount();
});

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
    .map((node) => node.textContent || "");
  assert.deepEqual(cells, [
    "now", "observation", "tester", "open", "",
    "then", "failed", "doctor", "closed", "later",
  ]);
  mounted.unmount();
});

test("a drill-in route survives the round trip and never outlives its view", () => {
  assert.deepEqual(parseUniverseRoute("#/items/42?project=3"), {
    view: "items", detail: "42", project: "3",
  });
  assert.equal(buildUniverseRoute("items", "3", "42"), "#/items/42?project=3");
  const odd = "YOK 7/a";
  assert.equal(
    parseUniverseRoute(buildUniverseRoute("items", "3", odd)).detail, odd,
  );
  assert.deepEqual(parseUniverseRoute("#/unknown/42"), {
    view: "overview", detail: null, project: null,
  });
  assert.equal(buildUniverseRoute("unknown", null, "42"), "#/overview");
});
