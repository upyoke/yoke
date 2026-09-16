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

test("Deployments is the one destination with tabs, Flows first", () => {
  // A facet that earned a name is a destination, so tabs stay the exception:
  // Deployments keeps them because a flow definition and a run of it are two
  // readings of one subject, and the definition is what an operator opens.
  const tabbed = NAV.filter((entry) => entry.tabs);
  assert.deepEqual(tabbed.map((entry) => entry.id), ["deployments"]);
  assert.deepEqual(
    tabbed[0].tabs,
    [{ id: "flows", label: "Flows" }, { id: "runs", label: "Runs" }],
  );
  assert.deepEqual(NAV_GROUPS.map((group) => group.id),
    ["focus", "settings", "diagnostics"]);
});

test("Runs is one eight-column table whose rows open the run page", async (t) => {
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
            member_items: [], gates: [],
          }],
          unfinished_count: 0,
          completed_match_count: 1,
          completed_loaded_count: 1,
          next_cursor: null,
          filters: { projects: [], statuses: [], environments: [], flows: [] },
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/deployments/runs", client);

  // "all" is one unfiltered call over the whole universe.
  assert.deepEqual(
    requests.find((request) => request.function === "deployment_runs.list"),
    {
      function: "deployment_runs.list",
      payload: { page: { page_size: 50 } },
    },
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "Release", "Project", "Carries", "Target",
      "Stages", "Status", "QA evidence", "When",
    ],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD").map(cellText),
    [
      "externalwebapp-prod-release", "externalwebapp", "environment run",
      "prod", "", "succeeded", "—", "then",
    ],
  );
  assert.equal(byClass(root, "secondary-muted")[0].textContent, "environment run");
  // The release is titled by its flow, with the run id beneath, and opens
  // the run's own page.
  assert.equal(byClass(root, "delivery-run-id")[0].textContent, "run-20260101-001");
  assert.equal(
    byClass(root, "delivery-run-title")[0].href,
    "#/deployments/runs/run-20260101-001?project=2",
  );
  assert.equal(byClass(root, "delivery-run-card").length, 0);
  // Every cell names its column, which is what lets a phone stack the row
  // instead of hiding status and stage progress off the right edge.
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TD")
      .map((node) => node.attributes.get("data-label")),
    [
      "Release", "Project", "Carries", "Target",
      "Stages", "Status", "QA evidence", "When",
    ],
  );
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
            gates: [{
              request_id: 4471,
              kind: "deployment_stage_approval",
              subject_context: {
                run_id: "run-20260726-001",
                stage: "approval",
                flow: { name: "hosted-release" },
                batch: { item_count: 1 },
                shipping: { target_environment: "prod" },
              },
              actions: ["approve", "reject"],
              approval_progress: {},
              can_act: true,
              authority_reason: "project owner",
              your_decision: null,
              decided_by_you: false,
            }],
          }],
          unfinished_count: 1,
          completed_match_count: 0,
          completed_loaded_count: 0,
          next_cursor: null,
          filters: { projects: [], statuses: [], environments: [], flows: [] },
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t,
    "#/deployments/runs?project=1",
    client,
  );

  assert.deepEqual(
    byClass(root, "delivery-run-stage").map(
      (node) => node.attributes.get("data-state"),
    ),
    ["complete", "active", "pending"],
  );
  assert.equal(byClass(root, "delivery-member")[0].href, "#/items/2228?project=1");
  assert.equal(byClass(root, "delivery-member")[0].textContent, "YOK-2228");
  assert.equal(byClass(root, "delivery-member")[0].title, "Ship the release");
  assert.equal(
    byClass(root, "delivery-run-title")[0].href,
    "#/deployments/runs/run-20260726-001?project=1",
  );
  // A suspended run reports its request, not the status it held when it
  // stopped.
  assert.equal(
    byClass(root, "delivery-run-status")[0].children[0].textContent, "awaiting approval",
  );
  const footer = byClass(root, "delivery-waiting-link")[0];
  assert.equal(footer.textContent, "1 run waiting on you →");
  assert.equal(footer.href, "#/inbox?project=1");
  assert.equal(byClass(root, "metric").length, 0);
  mounted.unmount();
});

test("a page-shaped list row shows flow, stages, and derived carried items", async (t) => {
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260911-001",
            project: "yoke",
            flow: "yoke-hosted-stage-typed-target",
            flow_name: "Stage (Warm-Gated, No CI Gate, Typed Target)",
            target_tier: "persistent",
            target_environment: "stage",
            status: "succeeded",
            current_stage: "complete",
            created_at: "2026-09-11T02:09:08Z",
            started_at: "2026-09-11T02:09:57Z",
            completed_at: "2026-09-11T02:34:23Z",
            member_items: [],
            carried_work: { items: [{ ref: "YOK-3080", item_id: 3207 }] },
            stages: [
              { name: "merged", state: "complete" },
              { name: "hosted-release", state: "complete" },
              { name: "warm-up", state: "complete" },
              { name: "complete", state: "complete" },
            ],
            gates: [],
          }],
          unfinished_count: 0,
          completed_match_count: 1,
          completed_loaded_count: 1,
          next_cursor: null,
          filters: {
            projects: [{ id: 1, label: "yoke" }],
            statuses: ["succeeded"],
            environments: ["stage"],
            flows: [{
              id: "yoke-hosted-stage-typed-target",
              label: "Stage (Warm-Gated, No CI Gate, Typed Target)",
            }],
          },
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/deployments/runs?project=1", client);
  const cells = allNodes(root).filter((node) => node.tagName === "TD").map(cellText);

  assert.equal(
    byClass(root, "delivery-run-title")[0].textContent,
    "Stage (Warm-Gated, No CI Gate, Typed Target)",
  );
  assert.equal(cells[2], "YOK-3080");
  assert.equal(byClass(root, "delivery-member")[0].textContent, "YOK-3080");
  assert.deepEqual(
    byClass(root, "delivery-run-stage").map(
      (node) => node.attributes.get("data-state"),
    ),
    ["complete", "complete", "complete", "complete"],
  );
  assert.equal(
    byClass(root, "delivery-run-title")[0].href,
    "#/deployments/runs/run-20260911-001?project=1",
  );
  mounted.unmount();
});
