import assert from "node:assert/strict";
import test from "node:test";
import { activityHistory } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_activity_history.js";
import { renderQaCaseDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_case_detail_view.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

test("case network, permission, and execution-read failures retain their meaning and retry", async () => {
  for (const failureAt of ["network", "permission", "qa.run.list"]) {
    const document = new FakeDocument();
    const host = document.createElement("main");
    let failed = true;
    const context = {
      document, isMounted: () => true,
      projects: () => [{ id: 1, slug: "demo" }],
      client: { async call(request) {
        if (failed && failureAt === "network") throw new Error("Connection interrupted");
        if (failed && failureAt === "permission") return {
          status: 403, envelope: { success: false, error: { message: "You do not have access to this case." } },
        };
        if (failed && request.function === failureAt) throw new Error("Execution history unavailable");
        if (request.function === "qa.requirement.get") return ok({ requirement: {
          id: 4, method_id: "command", instructions: "Check", expected_outcome: "Pass",
        } });
        return ok({ rows: [], needs_decision: [] });
      } },
    };
    await renderQaCaseDetail(context, host, "1", "4");
    assert.doesNotMatch(host.textContent, /never run|There is no QA case/);
    assert.match(host.textContent, failureAt === "permission" ? /do not have access/ : /unavailable|interrupted/);
    failed = false;
    byClass(host, "qa-case-retry")[0].dispatchEvent(new Event("click"));
    await settle();
    assert.match(host.textContent, /never run/);
    assert.equal(byClass(host, "qa-case-retry").length, 0);
  }
});

test("activity exposes older history with outcome/date filters and bounded pagination", () => {
  const document = new FakeDocument();
  const rows = Array.from({ length: 60 }, (_, index) => ({
    case_key: `case ${index}`, outcome: index % 2 ? "passed" : "failed",
    happened_at: index < 30 ? "2026-08-10T12:00:00" : "2026-08-09T12:00:00",
  }));
  let shown = [];
  const host = activityHistory({ document }, rows, (_body, page) => { shown = page; });
  const pager = byClass(host, "qa-history-pager")[0];
  assert.equal(shown.length, 25);
  assert.equal(pager.hidden, false);
  assert.equal(byClass(host, "item-filters").length, 0);
  assert.match(host.textContent, /Latest 500 cases per project/);
  const button = (label) => allNodes(host).find((node) => node.tagName === "BUTTON" && node.textContent === label);
  button("Next").dispatchEvent(new Event("click"));
  assert.equal(shown[0].case_key, "case 25");
  assert.ok(shown.some((row) => row.happened_at.includes("08-09")));
  const controls = allNodes(host).filter((node) => ["INPUT", "SELECT"].includes(node.tagName));
  controls[1].value = "failed";
  controls[1].dispatchEvent(new Event("change"));
  assert.equal(shown.length, 25);
  assert.ok(shown.every((row) => row.outcome === "failed"));
  controls[3].value = "2026-08-09";
  controls[3].dispatchEvent(new Event("change"));
  assert.equal(shown.length, 15);
  assert.equal(pager.hidden, true);
  assert.ok(shown.every((row) => row.happened_at.includes("08-09")));
  button("Clear filters").dispatchEvent(new Event("click"));
  assert.equal(shown[0].case_key, "case 0");
  assert.equal(pager.hidden, false);
});
