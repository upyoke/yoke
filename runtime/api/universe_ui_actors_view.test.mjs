import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, allNodes, byClass, settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const roster = {
  current_actor_id: 2,
  rows: [
    {
      id: 2, name: "Ben", kind: "human",
      roles: {
        org: [{ org: "Acme", role: "admin" }],
        projects: [{ project: "yoke", role: "owner" }],
      },
      identity: { email: "ben@example.test" },
    },
    {
      id: 7, name: "deploy-ci", kind: "system",
      roles: {
        org: [], projects: [{ project: "yoke", role: "deployment_ci" }],
      },
      identity: null,
    },
  ],
};

function client(answer) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return ok({ name: "Local", slug: "local" });
      }
      if (request.function === "projects.list") return ok({ rows: [] });
      if (request.function === "actors.roster") return answer();
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountActors(answer, mode = "local") {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/actors";
  const root = documentNode.createElement("div");
  const reads = client(answer);
  const mounted = mountUniverseApp(root, {
    client: reads,
    capabilities: { data: { portability: { mode } } },
  });
  await settle();
  await settle();
  return { root, reads, mounted };
}

function headings(root) {
  return allNodes(root).filter((node) => node.tagName === "TH")
    .map((node) => node.textContent);
}

test("Actors route renders the live roster with the shared page title", async () => {
  const { root, reads, mounted } = await mountActors(() => ok(roster), "hosted");
  assert.deepEqual(byClass(root, "page-head").map((node) => node.textContent), ["Actors"]);
  assert.equal(byClass(root, "actors-panel").length, 1);
  assert.deepEqual(headings(byClass(root, "actors-panel")[0]), [
    "Actor", "Kind", "Org role", "Project access", "Account",
  ]);
  assert.deepEqual(byClass(root, "actors-name").map((node) => node.textContent), [
    "Ben (you)", "deploy-ci",
  ]);
  assert.ok(byClass(root, "actors-panel")[0].textContent.includes("deployment_ci · yoke"));
  assert.ok(byClass(root, "actors-panel")[0].textContent.includes("ben@example.test"));
  assert.deepEqual(reads.requests.filter((request) => request.function === "actors.roster")
    .map((request) => request.payload), [{}]);
  const text = root.textContent;
  for (const removed of [
    "Grant access", "engine roles · two scopes", "Accounts come from Members.",
    "Actors · 4",
  ]) assert.ok(!text.includes(removed), removed);
  assert.equal(byClass(root, "panel-header").filter(
    (header) => header.textContent.includes("Actors"),
  ).length, 0);
  mounted.unmount();
});

test("local roster omits Account and explains a sole human actor", async () => {
  const onlyHuman = { ...roster, rows: [roster.rows[0]] };
  const { root, mounted } = await mountActors(() => ok(onlyHuman));
  assert.deepEqual(headings(byClass(root, "actors-panel")[0]), [
    "Actor", "Kind", "Org role", "Project access",
  ]);
  assert.equal(byClass(root, "actors-local-notice")[0].hidden, false);
  mounted.unmount();
});

test("empty, loading and refused reads retain a meaningful Actors screen", async () => {
  const empty = await mountActors(() => ok({ rows: [], current_actor_id: null }));
  assert.deepEqual(headings(byClass(empty.root, "actors-panel")[0]), [
    "Actor", "Kind", "Org role", "Project access",
  ]);
  assert.ok(empty.root.textContent.includes("No actors are registered"));
  empty.mounted.unmount();

  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/actors";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: client(() => pending),
  });
  await settle();
  assert.ok(root.textContent.includes("Loading actors…"));
  release(ok(roster));
  await settle();
  mounted.unmount();

  const failed = await mountActors(() => ({
    status: 403,
    envelope: { success: false, error: { message: "actor access denied" } },
  }));
  assert.ok(failed.root.textContent.includes("actor access denied"));
  assert.ok(failed.root.textContent.includes("Refresh the page"));
  failed.mounted.unmount();
});
