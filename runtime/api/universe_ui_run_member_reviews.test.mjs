// A release carries several members, and each one's pending review is its
// own. Offering member B's decision on member A's row asks a reviewer to
// rule on evidence that is not in front of them — and drawing the same
// request again at release level offers one decision twice on one page.
// Both the run page and the Overview card draw members and gates together,
// so both answer to the same rule.

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

const okEnvelope = (result) => ({ status: 200, envelope: { success: true, result } });

const MEMBERS = [
  { id: 2262, ref: "YOK-2228", project_sequence: 2228, title: "First member",
    project_id: 1, project: "yoke" },
  { id: 2263, ref: "YOK-2229", project_sequence: 2229, title: "Second member",
    project_id: 1, project: "yoke" },
];

// The acceptance waiting on a person answers for the SECOND member only.
const SECOND_MEMBER_REVIEW = {
  id: 5150,
  kind: "qa_needs_review",
  status: "pending",
  project_id: 1,
  subject_context: {
    requirement_id: 9,
    run_id: 5,
    subject: {
      kind: "deployment_run",
      deployment_member_item_id: 2263,
      item_ref: "YOK-2229",
      deployment_run_id: "run-20260726-001",
    },
    verdict_reason: "configured deployment stage requires authorized acceptance",
    artifacts: [],
    artifact_count: 0,
  },
  actions: ["reject", "approve"],
  deciders: [],
  can_act: true,
  decided_by_you: false,
  your_decision: null,
};

function client() {
  return {
    async call(request) {
      if (request.function === "organizations.get") return okEnvelope({ name: "Yoke" });
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: [{
            id: "run-20260726-001", project: "yoke", flow: "hosted-release",
            target_tier: "persistent", target_environment: "prod",
            status: "executing", current_stage: "item-qa",
            created_at: "2026-07-26T10:00:00Z", created_by: "usher",
            stages: [{ name: "item-qa", state: "active" }],
            member_items: MEMBERS,
            gates: [{
              request_id: SECOND_MEMBER_REVIEW.id,
              kind: SECOND_MEMBER_REVIEW.kind,
              subject_context: SECOND_MEMBER_REVIEW.subject_context,
              actions: SECOND_MEMBER_REVIEW.actions,
              approval_progress: {}, can_act: true,
              authority_reason: "project owner", deciders: [],
              your_decision: null, decided_by_you: false,
            }],
          }],
          unfinished_count: 1, completed_match_count: 0,
          completed_loaded_count: 0, next_cursor: null,
          filters: { projects: [], statuses: [], environments: [], flows: [] },
        });
      }
      if (request.function === "qa.activity.list") {
        return okEnvelope({ summary: { total: 0, counts: {} }, rows: [] });
      }
      if (request.function === "inbox.list") {
        return okEnvelope({ needs_decision: [SECOND_MEMBER_REVIEW] });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({ project: "1", sites: [], environments: [] });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

test("a pending review is offered on its own member's row only", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash =
    "#/deployments/runs/run-20260726-001?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: client() });
  await settle();
  await settle();
  await settle();

  // One decision, one set of controls, whichever member it answers for.
  const approvals = allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Approve",
  );
  assert.equal(approvals.length, 1);

  // The evidence sections are per member and in member order; only the
  // second one carries the decision.
  const sections = byClass(root, "carried-item-evidence");
  assert.equal(sections.length, 1, "only the answering member draws a section");
  const drawn = allNodes(sections[0]).map((node) => node.textContent || "").join(" ");
  assert.match(drawn, /YOK-2229|authorized acceptance/);
  assert.doesNotMatch(drawn, /YOK-2228/);
  mounted.unmount();
});


test("a Shipping card offers a member's review once as well", async (t) => {
  // The run page and the Shipping card compose the same two pieces — member
  // rows with their own reviews, then the release's gates — so a dedup that
  // covered only one of them left the other showing two Approve buttons for
  // one decision.
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/shipping?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: client() });
  await settle();
  await settle();
  await settle();

  // The member row drew it, so the release-level gate block had to skip it.
  const sections = byClass(root, "carried-item-evidence");
  assert.equal(sections.length, 1, "the answering member drew its own review");
  const approvals = allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Approve",
  );
  assert.equal(approvals.length, 1, "one decision, one Approve control");
  assert.equal(
    allNodes(sections[0]).filter(
      (node) => node.tagName === "BUTTON" && node.textContent === "Approve",
    ).length,
    1,
  );
  mounted.unmount();
});
