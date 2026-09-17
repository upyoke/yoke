// One decision is offered once on the run page, on the row that owns it.

// The run page: one deployment run in the page's shape, reached from a
// Deployments row, a Shipping card, or a release request.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { deploymentRequestRow } from "./universe_ui_inbox_test_support.mjs";

const okEnvelope = (result) => ({ status: 200, envelope: { success: true, result } });

function runRow(overrides = {}) {
  return {
    id: "run-20260726-001", project: "yoke", flow: "hosted-release",
    target_tier: "persistent", target_environment: "prod",
    release_lineage: "0.1.1+launch.379", status: "executing",
    current_stage: "approval", created_at: "2026-07-26T10:00:00Z",
    started_at: null, completed_at: null, created_by: "usher",
    stages: [
      { name: "build", state: "complete" },
      { name: "approval", state: "active" },
      { name: "release", state: "pending" },
    ],
    member_items: [{
      id: 2262, ref: "YOK-2228", project_sequence: 2228,
      title: "Ship the release", project_id: 1, project: "yoke",
    }],
    gates: [],
    ...overrides,
  };
}

function runClient(row, activityRows = [], itemActivityRows = [], siblingRows = []) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return okEnvelope({ name: "Yoke" });
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: row ? [row] : [],
          unfinished_count: row ? 1 : 0, completed_match_count: 0,
          completed_loaded_count: 0, next_cursor: null,
          filters: {
            projects: [], statuses: [], environments: [],
            flows: [{ id: "hosted-release", label: "Hosted release" }],
          },
        });
      }
      if (request.function === "qa.activity.list") {
        return okEnvelope({
          summary: { total: 0, counts: {} },
          rows: request.payload.item_ids ? itemActivityRows : activityRows,
        });
      }
      if (request.function === "inbox.list") {
        return okEnvelope({ needs_decision: [] });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({
          project: request.payload.project,
          sites: [],
          environments: [
            { site: "hosted", name: "prod", url: "https://upyoke.com",
              deploy_method: "workflow", health_check_url: null,
              last_deployed_at: "2026-07-26T10:20:00Z" },
          ],
        });
      }
      if (request.function === "deployment_runs.find_by_item") {
        return okEnvelope({
          item_id: request.target.item_id,
          fields: ["id", "status", "current_stage", "created_at"],
          rows: siblingRows,
        });
      }
      if (request.function === "qa.artifact.read") {
        return okEnvelope({
          artifact_id: request.payload.artifact_id, disposition: "ready",
          content_type: "image/png", content_base64: "aVZCT1J3MEs=",
        });
      }
      if (request.function === "decision_requests.resolve") {
        return okEnvelope({ request: { id: request.payload.request_id, status: "resolved" } });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
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
  await settle();
  return { root, mounted };
}

test("a member's QA review is offered once, on that member's row", async (t) => {
  // The release card draws each member with its own pending reviews, and the
  // same request also arrives in the run's gate list. Drawing both put one
  // decision on the page twice, with two sets of Approve buttons.
  const review = {
    id: 5150,
    kind: "qa_needs_review",
    status: "pending",
    project_id: 1,
    subject_context: {
      requirement_id: 9,
      run_id: 5,
      subject: {
        kind: "deployment_run",
        deployment_member_item_id: 2262,
        item_ref: "YOK-2228",
        deployment_run_id: "run-20260726-001",
      },
      verdict_reason: "the banner named the previous revision",
      artifacts: [],
      artifact_count: 0,
    },
    actions: ["reject", "approve"],
    deciders: [],
    can_act: true,
    decided_by_you: false,
    your_decision: null,
  };
  const client = runClient(runRow({
    gates: [{
      request_id: review.id, kind: review.kind,
      subject_context: review.subject_context, actions: review.actions,
      approval_progress: {}, can_act: true, authority_reason: "project owner",
      deciders: [], your_decision: null, decided_by_you: false,
    }],
  }));
  const inbox = client.call.bind(client);
  client.call = async (request) => (
    request.function === "inbox.list"
      ? okEnvelope({ needs_decision: [review] })
      : inbox(request)
  );
  const { root, mounted } = await mountAt(
    t, "#/deployments/runs/run-20260726-001?project=1", client,
  );

  const approvals = allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Approve",
  );
  assert.equal(approvals.length, 1, "one decision, one Approve control");
  // The heading still says the page is waiting: whose row the request sits
  // on does not change whether somebody has to answer it.
  assert.equal(
    byClass(root, "run-work")[0].children[0].textContent,
    "Waiting for a review",
  );
  // And it is the member's row that owns it, not a second release-level copy.
  const memberRow = byClass(root, "carried-item-evidence")[0];
  assert.ok(memberRow, "the member row draws its own review");
  assert.equal(
    allNodes(memberRow).filter(
      (node) => node.tagName === "BUTTON" && node.textContent === "Approve",
    ).length,
    1,
  );
  mounted.unmount();
});
