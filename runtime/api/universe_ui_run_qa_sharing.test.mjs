import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
} from "./universe_ui_dom_test_support.mjs";
import { member, readingContext } from "./universe_ui_carried_item_test_support.mjs";
import {
  appendCarriedItemEvidence,
  loadCarriedItemEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";
import { runQaSection } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_qa.js";
import {
  appendSharedPlanPointers,
  groupRunChecks,
  planGroupId,
  sharedOnlyVerdict,
} from "../../packages/yoke-core/src/yoke_core/ui/static/run_qa_sharing.js";
import { appendRemovedMembers } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_removed_members.js";
import {
  fillRunQaReviewChecks,
  runQaReviewCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/inbox_run_review.js";

const RUN = "run-20261017-002";
const GROUP = `${RUN}:1`;
const sharing = {
  plan_groups: [{
    group_id: GROUP, plan_id: 1, plan: "installer-campaign", plan_name: "Installer campaign",
    case_count: 2, closed: false, earlier_run_id: null,
    sharing_public_refs: ["YOK-3935", "YOK-3966"],
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
  execution_target_json: { deployment: { shared_plan: { plan_id: 1, group_id: GROUP } } },
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

test("Run QA draws a plan group once, labelled, and counts each live check once", () => {
  const documentNode = new FakeDocument();
  const section = runQaSection({ document: documentNode, projects: () => [] },
    { id: RUN, project_id: 1, gates: [] }, runChecks, null, { sharing });
  const [label] = byClass(section, "run-qa-shared-label");
  assert.equal(text(label), "Installer campaign · Covers: YOK-3935, YOK-3966");
  const [group] = byClass(section, "run-qa-shared-group");
  assert.equal(byClass(group, "run-qa-check").length, 2);
  assert.equal(text(byClass(section, "run-verdict")[0]), "2 of 3 passed · 1 queued");
  // The superseded attempt is history only.
  assert.match(text(byClass(section, "run-qa-history")[0]), /Earlier checks \(1\)/);
});

test("a plan-group-only item shows its group once; an item with item cases points at it", async () => {
  const documentNode = new FakeDocument();
  const context = readingContext(documentNode, client());
  const items = ["YOK-3935", "YOK-3966"].map((ref, at) => ({
    ...member(at + 1, ref), run_id: RUN,
  }));
  const facts = await loadCarriedItemEvidence(context, items);
  assert.deepEqual(facts.sharing.get(RUN), sharing);
  const [sharedOnlyHost, ownHost] = items.map((item) => {
    const host = documentNode.createElement("div");
    appendCarriedItemEvidence(context, host, { item, runId: RUN, facts });
    return host;
  });
  const naming = allNodes(sharedOnlyHost).filter((node) =>
    ownTextContent(node).includes("Installer campaign")).map(ownTextContent);
  assert.deepEqual(naming, ["Plan group: Installer campaign — see Run QA"]);
  assert.equal(byClass(sharedOnlyHost, "item-qa-shared-pointer").length, 0);
  assert.deepEqual(byClass(ownHost, "run-verdict").map(text), ["1 of 1 passed"]);
  assert.equal(byClass(ownHost, "run-qa-check").length, 1);
  assert.deepEqual(byClass(ownHost, "item-qa-shared-pointer").map(text),
    ["Plan group: Installer campaign — see Run QA"]);
  const [sharedOnly] = byClass(sharedOnlyHost, "item-qa-section");
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.css",
    import.meta.url,
  ), "utf8");
  assert.equal(sharedOnly.classList.contains("carried-item-qa-diagnostic"), true);
  assert.match(css, /\.carried-item-qa-diagnostic\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
  assert.match(css, /\.carried-item-qa-diagnostic\s*\{[^}]*overflow-wrap:\s*anywhere/);
});

test("a plan-group-only tile joins several groups; pointers stay one per group", () => {
  const plans = [{ plan_id: 1, plan_name: "Installer campaign" },
    { plan_id: 2, plan_name: "Setup walk" }];
  assert.equal(sharedOnlyVerdict(plans),
    "Plan groups: Installer campaign, Setup walk — see Run QA");
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  appendSharedPlanPointers(documentNode, host, plans);
  assert.deepEqual(byClass(host, "item-qa-shared-pointer").map(text), [
    "Plan group: Installer campaign — see Run QA",
    "Plan group: Setup walk — see Run QA",
  ]);
});

test("the Removed block names the checks its removal cancelled", () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  appendRemovedMembers({ document: documentNode }, host, { removed_member_items: [
    { ref: "YOK-3948", title: "Removed", project_id: 1, cancelled_check_count: 13,
      reason: "rides later" },
  ] }, 1);
  assert.equal(text(byClass(host, "carried-item-title")[0]), "Removed");
  assert.match(text(byClass(host, "release-removed-note")[0]), /^13 checks cancelled — rides later — rides/);
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /\.release-removed-note\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/);
  assert.match(css, /\.release-removed-note\s*\{[^}]*overflow-wrap:\s*anywhere/);
});

test("the Inbox run review groups plan group checks the same way", () => {
  const documentNode = new FakeDocument();
  const context = { document: documentNode, projects: () => [] };
  const row = { id: 5, kind: "qa_needs_review", status: "pending", project_id: 1,
    subject_context: { subject: { kind: "deployment_run", deployment_run_id: RUN } } };
  const card = runQaReviewCard(context, row, {});
  fillRunQaReviewChecks(context, card, row, { rows: runChecks, sharing });
  assert.equal(text(byClass(card, "run-qa-shared-label")[0]),
    "Installer campaign · Covers: YOK-3935, YOK-3966");
  assert.equal(byClass(byClass(card, "run-qa-shared-group")[0], "run-qa-check").length, 2);
});

test("a plan attached before its group forms draws its cases once", () => {
  const documentNode = new FakeDocument();
  const cases = ["first", "second"].map((key) => ({
    plan_id: 2, plan: "setup-walk", project_id: 1, case_key: key, method_name: "Terminal",
    qa_phase: "post_deploy", pending_obligation: true }));
  const pending = { plan_groups: [{ group_id: null, plan_id: 2, plan: "setup-walk",
    plan_name: "Setup walk", case_count: 2, pending: true, cases, closed: false,
    earlier_run_id: null, sharing_public_refs: ["YOK-1", "YOK-2"] }],
  removed_members: [] };
  const section = runQaSection({ document: documentNode, projects: () => [] },
    { id: RUN, project_id: 1, gates: [] }, [], null, { sharing: pending });
  const groups = byClass(section, "run-qa-shared-group");
  assert.equal(groups.length, 1);
  assert.equal(byClass(groups[0], "run-qa-check").length, pending.plan_groups[0].case_count);
  assert.match(text(byClass(section, "run-qa-shared-label")[0]), /Covers: YOK-1, YOK-2/);
  assert.equal(text(byClass(section, "run-verdict")[0]), "Not started");
  assert.deepEqual(byClass(section, "run-qa-check-outcome").map(text),
    ["Not started", "Not started"]);
  const host = documentNode.createElement("div");
  appendSharedPlanPointers(documentNode, host, pending.plan_groups);
  assert.deepEqual(byClass(host, "item-qa-shared-pointer").map(text),
    ["Plan group: Setup walk — see Run QA"]);
  assert.equal(byClass(host, "run-qa-check").length, 0);
});

test("one group per plan group id: closed, open and earlier-run groups stay apart", () => {
  const groups = {
    plan_groups: [
      { group_id: "run-old:1", plan_id: 1, plan_name: "Installer campaign", closed: true,
        earlier_run_id: "run-old", case_count: 1, sharing_public_refs: ["YOK-1"] },
      { group_id: `${RUN}:1`, plan_id: 1, plan_name: "Installer campaign", closed: true,
        earlier_run_id: null, case_count: 1, sharing_public_refs: ["YOK-2"] },
      { group_id: `${RUN}:2`, plan_id: 1, plan_name: "Installer campaign", closed: false,
        earlier_run_id: null, case_count: 1, sharing_public_refs: ["YOK-2", "YOK-3"] },
    ],
    removed_members: [],
  };
  const inGroup = (id, group) => check(id, { plan_id: 1,
    execution_target_json: { deployment: { shared_plan: { plan_id: 1, group_id: group } } } });
  const { own, groups: drawn } = groupRunChecks(
    [check(1), inGroup(2, `${RUN}:1`), inGroup(3, `${RUN}:2`)], groups);
  assert.deepEqual(own.map((row) => row.requirement_id), [1]);
  assert.deepEqual(drawn.map((group) => [group.label, group.checks.map((c) => c.requirement_id)]), [
    ["Installer campaign · Passed in run-old · Covers: YOK-1", []],
    ["Installer campaign · group 1 · Covers: YOK-2", [2]],
    ["Installer campaign · group 2 · Covers: YOK-2, YOK-3", [3]],
  ]);
  // A member's own row never joins a plan group, whatever its target says.
  assert.equal(planGroupId(inGroup(4, `${RUN}:2`)), `${RUN}:2`);
  assert.equal(planGroupId({ ...inGroup(5, `${RUN}:2`), deployment_member_public_ref: "YOK-2" }), null);
});
