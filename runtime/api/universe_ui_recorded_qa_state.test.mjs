import assert from "node:assert/strict";
import test from "node:test";

import { verificationPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_verification.js";
import { renderQaActivity } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import { renderQaCaseDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_case_detail_view.js";
import { runIdentityCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_identity.js";
import { classifyQaRow } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_state.js";
import { byClass, FakeDocument, visibleText } from "./universe_ui_dom_test_support.mjs";
import { detailItem, itemContext } from "./universe_ui_items_test_support.mjs";
import { activityRow, cardFor, member, memberEntry, readingClient, RUN_ID } from "./universe_ui_carried_item_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

function capturedContext() {
  const document = new FakeDocument();
  const item = detailItem("dash");
  const requirement = { id: 5, public_ref: item.public_ref, qa_phase: "verification",
    qa_kind: "method_case", method_id: "browser-inspection", method_name: "Browser inspection",
    instructions: "Inspect the rendered page", expected_outcome: "The page is readable" };
  const row = { ...requirement, requirement_id: requirement.id, run_id: 12,
    project: "acme", outcome: "captured", execution_status: "captured",
    proof_summary: "1 screenshot", artifacts: [], happened_at: new Date().toISOString() };
  item.qa_requirements = [{ ...row, id: requirement.id }];
  item.qa_plan_attachments = [];
  const context = itemContext(document, async (request) => {
    if (request.function === "inbox.list") return ok({ needs_decision: [] });
    if (request.function === "qa.requirement.get") return ok({ requirement });
    if (request.function === "items.detail.get") return ok({ item });
    if (request.function === "qa.run.list") return ok({ rows: [
      { id: row.run_id, execution_status: "captured", created_at: row.happened_at },
      { id: 11, verdict: "fail" },
    ] });
    if (request.function === "qa.activity.list") return ok({ rows: [row],
      summary: { total: 1, counts: { captured: 1 } } });
    throw new Error(`unexpected function ${request.function}`);
  });
  return { context, item, requirement, row };
}

test("item Verification and QA activity show the latest captured attempt", async () => {
  const { context, item, row } = capturedContext();
  const panel = verificationPanel(context, item);
  assert.match(visibleText(panel), /captured/);
  assert.doesNotMatch(visibleText(panel), /queued/);
  const main = context.document.createElement("main");
  await renderQaActivity(context, main, [String(item.project.id)]);
  assert.equal(byClass(main, "qa-activity-row").length, 1);
  assert.match(visibleText(main), /captured/);
  assert.equal(classifyQaRow({ ...row, deployment_run_id: "run-example" }).label, "captured");
});

test("QA activity case route reads its newest recorded run without a plan", async () => {
  const { context, requirement } = capturedContext();
  const main = context.document.createElement("main");
  await renderQaCaseDetail(context, main, "acme", requirement.id);
  assert.equal(byClass(main, "qa-outcome")[0].textContent, "captured");
  assert.match(visibleText(main), /captured/);
  assert.match(visibleText(main), /Earlier executions/);
  assert.doesNotMatch(visibleText(main), /never run|No materialized case activity/);
});

test("a no-obligation member has settled Item QA and its recorded reason", async () => {
  const reason = "Only command teaching changed; there is no deployed behavior to inspect.";
  const client = readingClient({ rows: [activityRow({ qa_kind: "post_deploy_no_obligation",
    public_ref: "SAMPLE-1", deployment_run_id: RUN_ID, qa_phase: "post_deploy", instructions: reason, method_id: null, method_name: null,
    outcome: "no_obligation", artifacts: [], run_id: null })] });
  const prefix = "SAMPLE";
  const { card } = await cardFor(new FakeDocument(), [member(1896, `${prefix}-1`)], client);
  const section = byClass(memberEntry(card), "item-qa-section")[0];
  assert.ok(section);
  assert.match(visibleText(section), /Item QA.*No obligation/);
  assert.match(visibleText(section), new RegExp(reason));
  assert.doesNotMatch(visibleText(section), /queued|0 of 0 passed/);
  assert.equal(byClass(section, "is-approved").length, 1);
});

test("Run Identity shows the recorded artifact or explains its source-only identity", () => {
  const context = { document: new FakeDocument() };
  const recorded = runIdentityCard(context, { artifact_identity: "sha256:immutable" }, null);
  assert.match(visibleText(recorded), /sha256:immutable/);
  const source = runIdentityCard(context, { release_lineage: "a".repeat(40) }, null);
  assert.match(visibleText(source), /No artifact identity recorded; this run pins a source revision/);
  const empty = runIdentityCard(context, {}, null);
  assert.match(visibleText(empty), /No artifact identity or source revision recorded/);
});
