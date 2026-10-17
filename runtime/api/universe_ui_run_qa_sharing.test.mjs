import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";
import { member, readingContext } from "./universe_ui_carried_item_test_support.mjs";
import {
  appendCarriedItemEvidence,
  loadCarriedItemEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { runQaSection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_qa.js";
import { appendRemovedMembers } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_removed_members.js";
import {
  fillRunQaReviewChecks,
  runQaReviewCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/inbox_run_review.js";

const RUN = "run-20261017-002";
const sharing = {
  shared_plans: [{
    plan_id: 1, plan: "installer-campaign", plan_name: "Installer campaign",
    case_count: 2, sharing_public_refs: ["YOK-3935", "YOK-3966"],
  }],
  removed_members: [{ public_ref: "YOK-3948", cancelled_count: 13 }],
};

function check(id, overrides = {}) {
  return {
    requirement_id: id, deployment_run_id: RUN, project: "yoke",
    deployment_member_public_ref: null, method_name: "Terminal",
    case_key: `case-${id}`, outcome: "passed", artifacts: [], ...overrides,
  };
}

const shared = (id, overrides) => check(id, {
  plan_id: 1,
  execution_target_json: { deployment: { shared_plan: { plan_id: 1 } } },
  ...overrides,
});

// One release-wide check, two shared checks, and a superseded shared attempt.
const runChecks = [
  check(1),
  shared(2),
  shared(3, { outcome: "queued" }),
  shared(4, { outcome: "failed", superseded_by_requirement_id: 3 }),
];

function text(node) {
  return node.textContent;
}

function client() {
  return {
    async call(request) {
      if (request.function === "qa.activity.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [check(10, { deployment_member_public_ref: "YOK-3966" })],
          item_selection: null,
          run_sharing: { [RUN]: sharing },
        } } };
      }
      if (request.function === "inbox.list") {
        return { status: 200, envelope: { success: true, result: { needs_decision: [] } } };
      }
      throw new Error(`unexpected ${request.function}`);
    },
  };
}

test("Run QA draws a shared plan once, labelled, and counts each live check once", () => {
  const documentNode = new FakeDocument();
  const section = runQaSection({ document: documentNode, projects: () => [] },
    { id: RUN, project_id: 1, gates: [] }, runChecks, null, { sharing });
  const [label] = byClass(section, "run-qa-shared-label");
  assert.equal(text(label), "Installer campaign · Shared by YOK-3935, YOK-3966");
  const [group] = byClass(section, "run-qa-shared-group");
  assert.equal(byClass(group, "run-qa-check").length, 2);
  assert.equal(text(byClass(section, "run-verdict")[0]), "2 of 3 passed · 1 queued");
  // The superseded attempt is history only.
  assert.match(text(byClass(section, "run-qa-history")[0]), /Earlier checks \(1\)/);
});

test("items point at the shared plan, keep a tile when shared-only, and show removal", async () => {
  const documentNode = new FakeDocument();
  const context = readingContext(documentNode, client());
  const items = ["YOK-3935", "YOK-3966", "YOK-3948"].map((ref, at) => ({
    ...member(at + 1, ref), run_id: RUN,
  }));
  const facts = await loadCarriedItemEvidence(context, items);
  assert.deepEqual(facts.sharing.get(RUN), sharing);
  const host = documentNode.createElement("div");
  for (const item of items) {
    appendCarriedItemEvidence(context, host, { item, runId: RUN, facts });
  }
  const pointers = byClass(host, "item-qa-shared-pointer").map(text);
  assert.deepEqual(pointers, [
    "shares Installer campaign (2) — see Run QA",
    "shares Installer campaign (2) — see Run QA",
  ]);
  const verdicts = byClass(host, "run-verdict").map(text);
  assert.deepEqual(verdicts, ["0 own checks, shares Installer campaign", "1 of 1 passed"]);
  assert.deepEqual(byClass(host, "carried-item-removed").map(text),
    ["Removed from this release · 13 checks cancelled"]);
});

test("the Removed block names the checks its removal cancelled", () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  appendRemovedMembers({ document: documentNode }, host, { removed_member_items: [
    { ref: "YOK-3948", title: "Removed", project_id: 1, cancelled_check_count: 13,
      reason: "rides later" },
  ] }, 1);
  assert.match(text(byClass(host, "release-removed-note")[0]), /^13 checks cancelled — rides later — rides/);
});

test("the Inbox run review groups shared checks the same way", () => {
  const documentNode = new FakeDocument();
  const context = { document: documentNode, projects: () => [] };
  const row = { id: 5, kind: "qa_needs_review", status: "pending", project_id: 1,
    subject_context: { subject: { kind: "deployment_run", deployment_run_id: RUN } } };
  const card = runQaReviewCard(context, row, {});
  fillRunQaReviewChecks(context, card, row, { rows: runChecks, sharing });
  assert.equal(text(byClass(card, "run-qa-shared-label")[0]),
    "Installer campaign · Shared by YOK-3935, YOK-3966");
  assert.equal(byClass(byClass(card, "run-qa-shared-group")[0], "run-qa-check").length, 2);
});
