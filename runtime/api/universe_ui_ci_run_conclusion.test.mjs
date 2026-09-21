import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import { verificationCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_verification.js";
import { renderQaActivity } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";
import { ok } from "./universe_ui_qa_view_data_test_support.mjs";
import {
  activityRow,
  cardFor,
  member,
  memberEntry,
  readingClient,
} from "./universe_ui_carried_item_test_support.mjs";

const SHA = "f81d1ad1a61c0000000000000000000000000000";
const RUN_URL = "https://github.test/upyoke/yoke/actions/runs/399";

function ciRequirement(overrides = {}) {
  return {
    id: 8,
    run_id: 107,
    requirement_source: "backend-suite",
    plan_case_key: "backend-suite",
    method_id: "command",
    method_name: "Command",
    outcome: "passed",
    artifacts: [],
    recorded_head_sha: SHA,
    run_url: RUN_URL,
    ci_conclusion: "success",
    proof_summary: `verified ${SHA.slice(0, 12)} · GitHub Actions run`,
    ...overrides,
  };
}

test("a passing CI check without artifacts links the Actions run", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("dash");
  item.qa_plan_attachments = [];
  item.qa_requirements = [ciRequirement()];
  renderItemDetailView(itemContext(documentNode, async (request) => ({
    status: 200,
    envelope: {
      success: true,
      result: request.function === "items.detail.get"
        ? { item }
        : { execution: { execution_document: { slug: "CURRENT-PLAN" } } },
    },
  })), root, "7", "ACM-22");
  await settle();

  const rendered = itemText(root);
  assert.match(rendered, /verified f81d1ad1a61c/);
  assert.doesNotMatch(rendered, /This run attached no artifacts/);
  const links = byClass(root, "item-proof-link-out");
  const actions = links.find((node) => /GitHub Actions run/.test(node.textContent));
  assert.ok(actions, "the CI conclusion is a link");
  assert.equal(actions.href, RUN_URL);
});

test("captured without artifacts is still missing evidence, not a CI run", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem("dash");
  item.qa_plan_attachments = [];
  item.qa_requirements = [{
    id: 9,
    run_id: 44,
    method_id: "browser-inspection",
    method_name: "Browser inspection",
    execution_status: "captured",
    artifacts: [],
    proof_summary: "",
  }];
  renderItemDetailView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: { success: true, result: { item } },
  })), root, "7", "ACM-22");
  await settle();

  assert.match(itemText(root), /This run attached no artifacts/);
  assert.equal(
    byClass(root, "item-proof-link-out").filter(
      (node) => /GitHub Actions run/.test(node.textContent),
    ).length,
    0,
  );
});

test("the run verification card links a CI check that has no screenshots", () => {
  const documentNode = new FakeDocument();
  const context = { document: documentNode, client: { call: async () => ({}) } };
  const card = verificationCard(context, [{
    requirement_id: 8,
    case_key: "backend-suite",
    method_name: "Command",
    outcome: "passed",
    artifacts: [],
    run_url: RUN_URL,
    recorded_head_sha: SHA,
    ci_conclusion: "success",
  }]);
  assert.match(card.textContent, /1 of 1 passed/);
  const link = byClass(card, "run-check-conclusion")[0];
  assert.equal(link.tagName.toLowerCase(), "a");
  assert.equal(link.href, RUN_URL);
  assert.match(link.textContent, /GitHub Actions run/);
});

test("activity evidence summary is the Actions run when a CI row has no artifacts", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  await renderQaActivity({
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate: () => {},
    capabilities: {},
    client: {
      async call(request) {
        if (request.function === "inbox.list") {
          return ok({ needs_decision: [], messages: [] });
        }
        if (request.function === "qa.activity.list") {
          return ok({
            summary: { total: 1, counts: { passed: 1 } },
            rows: [{
              requirement_id: 8,
              plan_id: 9,
              plan: "release-readiness",
              project: "yoke",
              case_key: "backend-suite",
              method_id: "command",
              method_name: "Command",
              outcome: "passed",
              evidence_count: 0,
              artifacts: [],
              run_url: RUN_URL,
              recorded_head_sha: SHA,
              ci_conclusion: "success",
              proof_summary: `verified ${SHA.slice(0, 12)} · GitHub Actions run`,
              happened_at: new Date().toISOString(),
            }],
          });
        }
        return ok({});
      },
    },
  }, root, "all");
  await settle();

  const summary = byClass(root, "qa-activity-evidence-summary")[0];
  assert.equal(summary.tagName.toLowerCase(), "a");
  assert.equal(summary.href, RUN_URL);
  assert.match(summary.textContent, /verified f81d1ad1a61c/);
});

test("a carried CI check without artifacts is a link, not an empty strip", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow({
      artifacts: [],
      evidence_count: 0,
      outcome: "passed",
      case_key: "backend-suite",
      method_name: "Command",
      run_url: RUN_URL,
      recorded_head_sha: SHA,
      ci_conclusion: "success",
      proof_summary: `verified ${SHA.slice(0, 12)} · GitHub Actions run`,
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const caption = byClass(evidence, "carried-item-evidence-caption")[0].textContent;
  assert.match(caption, /never asked/);
  assert.match(caption, /verified before merge/);
  assert.doesNotMatch(caption, /verified this release/);
  assert.equal(byClass(evidence, "review-shot").length, 0);
  const link = byClass(evidence, "carried-item-run-conclusion")[0];
  assert.equal(link.href, RUN_URL);
  assert.match(link.textContent, /GitHub Actions run/);
});
