import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, allNodes, byClass, settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const roster = {
  current_actor_id: 2,
  role_descriptions: { deployment_ci: "Release tags and deploys." },
  machine_only_roles: ["deployment_ci"],
  bootstrap_only_roles: [],
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

async function mountTeam(answer, mode = "local") {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/team";
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

// Header labels without the active sort arrow.
function headings(root) {
  return allNodes(root).filter((node) => node.tagName === "TH")
    .map((node) => node.textContent.replace(/ [↑↓]$/, ""));
}

const panelTitles = (root) => byClass(root, "actors-panel")
  .map((panel) => byClass(panel, "panel-header")[0].textContent);

test("Team route groups people and machine accounts with readable grants", async () => {
  const { root, reads, mounted } = await mountTeam(() => ok(roster), "hosted");
  assert.deepEqual(byClass(root, "page-head").map((node) => node.textContent), ["Team"]);
  assert.deepEqual(panelTitles(root), ["People· 1", "Machine accounts· 1"]);
  const [people, machines] = byClass(root, "actors-panel");
  assert.deepEqual(headings(people), [
    "Actor", "State", "Org role", "Project access", "Member email", "API keys", "Action",
  ]);
  assert.deepEqual(headings(machines), ["Actor", "State", "Grants", "API keys"]);
  assert.deepEqual(byClass(root, "actors-name").map((node) => node.textContent), [
    "Ben (you)", "deploy-ci",
  ]);
  assert.deepEqual(byClass(people, "actors-access").map((node) => node.textContent), [
    "All projects · from org admin", "yoke · owner",
  ]);
  assert.ok(people.textContent.includes("ben@example.test"));
  assert.deepEqual(byClass(machines, "actors-grant").map((node) => node.textContent), [
    "Project · yokedeployment_cimachine-onlyRelease tags and deploys.",
  ]);
  assert.deepEqual(reads.requests.filter((request) => request.function === "actors.roster")
    .map((request) => request.payload), [{}]);
  const text = root.textContent;
  for (const removed of [
    "Grant access", "engine roles · two scopes", "Accounts come from Members.",
    "Team · 4", "deployment_ci · yoke", "Account",
    "Everyone and everything that can act in this universe",
  ]) assert.ok(!text.includes(removed), removed);
  mounted.unmount();
});

test("local roster omits Member email and names a sole human actor", async () => {
  const onlyHuman = { ...roster, rows: [roster.rows[0]] };
  const { root, mounted } = await mountTeam(() => ok(onlyHuman));
  assert.deepEqual(panelTitles(root), ["People· 1"]);
  assert.deepEqual(headings(byClass(root, "actors-panel")[0]), [
    "Actor", "State", "Org role", "Project access", "API keys", "Action",
  ]);
  const notice = byClass(root, "actors-local-notice")[0];
  assert.equal(notice.hidden, false);
  assert.equal(notice.textContent, "You are the only actor in this universe.");
  mounted.unmount();
});

test("empty, loading and refused reads retain a meaningful Team screen", async () => {
  const empty = await mountTeam(() => ok({ rows: [], current_actor_id: null }));
  assert.equal(byClass(empty.root, "actors-panel").length, 0);
  assert.ok(empty.root.textContent.includes("No actors are registered"));
  empty.mounted.unmount();

  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/team";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: client(() => pending),
  });
  await settle();
  assert.ok(root.textContent.includes("Loading team…"));
  release(ok(roster));
  await settle();
  mounted.unmount();

  const failed = await mountTeam(() => ({
    status: 403,
    envelope: { success: false, error: { message: "actor access denied" } },
  }));
  assert.ok(failed.root.textContent.includes("actor access denied"));
  assert.ok(failed.root.textContent.includes("Refresh the page"));
  failed.mounted.unmount();
});
