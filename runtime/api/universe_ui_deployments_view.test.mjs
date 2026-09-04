import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  NAV,
  NAV_GROUPS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  DETAIL_RENDERERS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

test("navigation is three groups, and every entry declares one", () => {
  assert.deepEqual(
    NAV.map(({ id, icon, label, scope, group }) => [id, icon, label, scope, group]),
    [
      ["overview", "⊞", "Overview", "multi", "focus"],
      ["sessions", "◈", "Sessions", "multi", "focus"],
      ["inbox", "✉", "Inbox", "multi", "focus"],

      ["organization", "⛭", "Universe", "none", "settings"],
      ["workflows", "⚗", "Workflows", "none", "settings"],
      ["projects", "▤", "Projects", "none", "settings"],
      ["github", "⎇", "GitHub", "single", "settings"],
      ["actors", "⚇", "Actors", "none", "settings"],
      ["members", "⚉", "Members", "none", "settings"],
      ["billing", "▧", "Billing", "none", "settings"],

      ["strategy", "❖", "Strategy", "multi", "diagnostics"],
      ["items", "≣", "Items", "multi", "diagnostics"],
      ["deployments", "⬈", "Deployments", "multi", "diagnostics"],
      ["environments", "◇", "Environments", "multi", "diagnostics"],
      ["flows", "⇉", "Flows", "multi", "diagnostics"],
      ["databases", "▤", "Databases", "multi", "diagnostics"],
      ["infrastructure", "▥", "Infrastructure", "multi", "diagnostics"],
      ["qa-methods", "◉", "QA methods", "multi", "diagnostics"],
      ["qa-plans", "◎", "QA plans", "multi", "diagnostics"],
      ["qa-activity", "◍", "QA activity", "multi", "diagnostics"],
      ["capabilities", "⚿", "Capabilities", "multi", "diagnostics"],
      ["packs", "◫", "Packs", "none", "diagnostics"],
      ["architecture", "▦", "Architecture", "single", "diagnostics"],
      ["messages", "✦", "Messages", "multi", "diagnostics"],
      ["events", "≋", "Events", "multi", "diagnostics"],
      ["doctor", "♥", "Doctor", "multi", "diagnostics"],
      ["ouroboros", "∞", "Ouroboros", "multi", "diagnostics"],
      ["machines", "▣", "Machines", "multi", "diagnostics"],
    ],
  );
});

test("no destination declares tabs, and the group order is fixed", () => {
  // A tab was one facet of a view's single concept. Every facet that earned a
  // name is a destination now, so a surviving `tabs` roster would be a second
  // way to reach something the sidebar already reaches.
  for (const entry of NAV) assert.equal(entry.tabs, undefined, entry.id);
  assert.deepEqual(NAV_GROUPS.map((group) => group.id),
    ["focus", "settings", "diagnostics"]);
});

test("Runs is the prototype's one seven-column execution table", async (t) => {
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: [
            { id: 1, slug: "yoke", name: "Yoke" },
            { id: 2, slug: "externalwebapp", name: "ExternalWebapp" },
          ],
        });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260101-001", project: "externalwebapp",
            flow: "externalwebapp-prod-release",
            target_tier: "persistent", target_environment: "prod",
            release_lineage: null, status: "succeeded",
            current_stage: "complete", created_at: "then",
            started_at: null, completed_at: null, created_by: "usher",
            stage_index: 1, stage_count: 2,
            stages: [
              { name: "build", state: "complete" },
              { name: "release", state: "complete" },
            ],
            member_items: [], waiting_on_approval: false,
          }],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/deployments", client);

  // "all" is one unfiltered call over the whole universe.
  assert.deepEqual(
    requests.find((request) => request.function === "deployment_runs.list"),
    { function: "deployment_runs.list", payload: {} },
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "Run", "Project", "Originating item", "Target",
      "Stages", "Status", "When",
    ],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD").map(cellText),
    [
      "run-20260101-001", "externalwebapp", "environment run",
      "prod", "", "succeeded", "then",
    ],
  );
  assert.equal(byClass(root, "secondary-muted")[0].textContent, "environment run");
  assert.equal(byClass(root, "delivery-run-card").length, 0);
  assert.deepEqual(
    byClass(root, "delivery-run-stage").map(
      (node) => node.attributes.get("data-state"),
    ),
    ["complete", "complete"],
  );
  mounted.unmount();
});

test("an approval-paused table row links its item and Inbox decision", async (t) => {
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260726-001", project: "yoke",
            flow: "hosted-release",
            target_tier: "persistent", target_environment: "prod",
            release_lineage: "release-17", status: "executing",
            current_stage: "approval", created_at: "2026-07-26T10:00:00Z",
            created_by: "usher", stage_index: 1, stage_count: 3,
            stages: [
              { name: "build", state: "complete" },
              { name: "approval", state: "active" },
              { name: "release", state: "pending" },
            ],
            member_items: [{
              id: 2262, ref: "YOK-2228", project_sequence: 2228,
              title: "Ship the release", project_id: 1,
              project: "yoke", status: "implemented",
            }],
            waiting_on_approval: true,
          }],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t,
    "#/deployments?project=1",
    client,
  );

  assert.deepEqual(
    byClass(root, "delivery-run-stage").map(
      (node) => node.attributes.get("data-state"),
    ),
    ["complete", "active", "pending"],
  );
  assert.equal(byClass(root, "delivery-member")[0].href, "#/items/2228?project=1");
  assert.equal(
    byClass(root, "delivery-member")[0].textContent,
    "YOK-2228 · Ship the release",
  );
  const footer = byClass(root, "delivery-waiting-link")[0];
  assert.equal(footer.textContent, "1 run waiting on you →");
  assert.equal(footer.href, "#/inbox?project=1");
  assert.equal(byClass(root, "metric").length, 0);
  mounted.unmount();
});
