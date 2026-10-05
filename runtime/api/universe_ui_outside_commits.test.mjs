import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument, byClass, allNodes, settle } from "./universe_ui_dom_test_support.mjs";
import { shippingRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { renderRunsTable } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_delivery_runs_table.js";
import { renderRunDetailView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_run_detail.js";
import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { outsideCommitCount } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_outside_commits.js";

const first = "a".repeat(40);
const second = "b".repeat(40);
function run() {
  return {
    id: "run-outside-work", project: "sample", flow: "release", status: "executing",
    current_stage: "deploy", gates: [], member_items: [], stages: [],
    carried_work: {
      derivation: { contents_known: true, status: "derived", reason: "complete" },
      items: [], commits: [first], commit_subjects: { [first]: "Fix <navigation>" },
      commit_authors: { [first]: "A maintainer" },
      bound_projects: [{
        project: "consumer", project_id: 2, commits: [second], items: [],
        commit_subjects: { [second]: "Install Yoke operating layer" },
        commit_authors: { [second]: "Automation" },
      }],
    },
  };
}

function context(row = run()) {
  const document = new FakeDocument();
  return {
    document, isMounted: () => true, projects: () => [{ id: 1, slug: "sample" }],
    client: { async call(request) {
      const result = request.function === "deployment_runs.list"
        ? { rows: [row], filters: { flows: [] } }
        : request.function === "inbox.list"
          ? { needs_decision: [{
            id: 10, project_id: 1, kind: "deployment_stage_approval", status: "pending",
            title: "Approve release", actions: [], can_act: false,
            subject_context: { run_id: row.id, carried: row.carried_work },
          }], messages: [], notices: [] }
          : { rows: [] };
      return { status: 200, envelope: { success: true, result } };
    } },
  };
}

function assertOutside(host) {
  assert.equal(byClass(host, "outside-commits-summary")[0]?.textContent,
    "Also includes 2 commits made outside Yoke");
  assert.deepEqual(byClass(host, "outside-commits-project-name").map((node) => node.textContent),
    ["sample", "consumer"]);
  assert.match(host.textContent, /aaaaaaaaaaaaFix <navigation>A maintainer/);
  assert.match(host.textContent, /bbbbbbbbbbbbInstall Yoke operating layerAutomation/);
  const details = byClass(host, "outside-commits")[0];
  assert.equal(details.tagName, "DETAILS");
  assert.equal(details.getAttribute("open"), null);
  assert.equal(allNodes(details).filter((node) => node.tagName === "SUMMARY").length, 1);
}

test("Shipping shows outside work even when no items are attached", () => {
  const ctx = context();
  const card = shippingRunCard(ctx, run(), "all");
  assertOutside(card);
  assert.ok(!card.textContent.includes("environment run"));
  assert.equal(outsideCommitCount(run()), 2);
});

test("Runs table carries the same expandable list", () => {
  const ctx = context();
  const host = ctx.document.createElement("div");
  renderRunsTable(ctx, host, [run()], {
    facts: {}, flowLabels: new Map(), scope: "all", reload() {},
  });
  assertOutside(host);
  assert.ok(!host.textContent.includes("environment run"));
});

test("run page carries outside work", async () => {
  const ctx = context();
  const host = ctx.document.createElement("div");
  await renderRunDetailView(ctx, host, "all", run().id);
  assertOutside(host);
});

test("release approval carries outside work without attached items", async () => {
  const ctx = context();
  const host = ctx.document.createElement("div");
  renderInboxView(ctx, host, "all");
  await settle();
  assertOutside(host);
});

test("older serving responses and empty releases have no invented outside work", () => {
  const ctx = context();
  const row = { ...run(), carried_work: { items: [] } };
  const card = shippingRunCard(ctx, row, "all");
  assert.equal(byClass(card, "outside-commits").length, 0);
  assert.match(card.textContent, /environment run/);
});
