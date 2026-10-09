import assert from "node:assert/strict";
import test from "node:test";
import { effectiveChecks } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_run_evidence.js";
import { itemQaChecks } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_qa.js";
import { createEventsHistoryLoader } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_events_history_loader.js";

const first = "2060-10-08T00:00:00.123456Z";
const later = "2060-10-08T00:00:00.123457Z";
const equal = "2060-10-08T05:45:00.123456+05:45";
const opaque = "2060-10-08T00:00:00+09:00 unchanged";
const check = (stamp, extra = {}) => ({ requirement_id: 1, happened_at: stamp,
  run_id: 17, deployment_run_id: "clock-run", outcome: "passed", reason: opaque, ...extra });

test("effective checks rank actual microseconds and retain first-arrival equal-instant ties", () => {
  const old = check(first, { run_id: 100 });
  const current = check(later, { run_id: 1 });
  assert.deepEqual(effectiveChecks([old, current]), [current]);
  assert.deepEqual(effectiveChecks([current, old]), [current]);
  const tied = check(equal, { run_id: 999 });
  assert.deepEqual(effectiveChecks([old, tied]), [old]);
  assert.equal(old.reason, opaque);
});

test("missing clocks retain numeric run ranking; a removed requirement cannot replace a live one", () => {
  const small = check(null, { run_id: 17 });
  const large = check(null, { run_id: 18 });
  assert.deepEqual(effectiveChecks([small, large]), [large]);
  const live = check(first);
  const removed = check(later, { retracted_at: later });
  assert.deepEqual(effectiveChecks([live, removed]), [live]);
  assert.throws(() => effectiveChecks([check("2060-10-08")]), /invalid_instant/);
});

test("carried history sorts microseconds while equivalent-offset ties retain arrival order", () => {
  const old = check(first, { requirement_id: 1, retracted_at: later });
  const newer = check(later, { requirement_id: 2, retracted_at: later });
  const tied = check(equal, { requirement_id: 3, retracted_at: later });
  const result = itemQaChecks([old, newer, tied], { runId: "clock-run" });
  assert.deepEqual(result.current, []);
  assert.deepEqual(result.history, [newer, old, tied]);
});

async function timeline(pages) {
  let call = 0;
  const context = { isMounted: () => true, client: { call: async () => ({
    status: 200, envelope: { success: true, result: { rows: pages[call++], next_cursor: null } },
  }) } };
  const loader = createEventsHistoryLoader({ context, buckets: pages.map((_, id) => id) });
  await loader.start();
  return loader.state().rows;
}

test("project event pages merge by exact instant and stable bucket/arrival for offset aliases", async () => {
  const old = { created_at: first, context: opaque };
  const tied = { created_at: equal };
  const newer = { created_at: later };
  assert.deepEqual(await timeline([[old], [tied, newer]]), [newer, old, tied]);
  assert.equal(old.context, opaque);
  await assert.rejects(timeline([[{ created_at: "2060-10-08" }]]), /invalid_instant/);
});


import { releasedHoldingHistory } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.js";

test("released holding groups select microseconds, retain equal-offset ties and count occurrences", () => {
  const old = { target_key: "clock-holding", released_at: first, reason: opaque };
  const newer = { ...old, released_at: later, reason: "latest" };
  const tied = { ...old, released_at: equal, reason: "equal" };
  assert.deepEqual(releasedHoldingHistory([old, newer]), [{ ...newer, occurrence_count: 2 }]);
  assert.deepEqual(releasedHoldingHistory([old, tied]), [{ ...old, occurrence_count: 2 }]);
  const missing = { ...old, released_at: null };
  const beforeEpoch = { ...old, released_at: "1969-12-31T23:59:59.999999Z" };
  assert.deepEqual(releasedHoldingHistory([missing, beforeEpoch]), [{ ...beforeEpoch, occurrence_count: 2 }]);
  assert.throws(() => releasedHoldingHistory([old, { ...old, released_at: "" }]), /invalid_instant/);
});


import { renderQaPlans } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_plans.js";
import { renderQaMethodDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_method_detail.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

async function renderedPlanOrder(detail, clocks) {
  const rows = clocks.map(([slug, last_at], index) => ({
    id: index + 1, slug, project: "demo", case_keys: [], case_count: 0,
    method_is_complete_plan: true, attachments: [], last_at, last_outcome: "passed",
    outcome_summary: { state: "passed", counts: { passed: 1 }, last_at },
  }));
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const context = { document: documentNode, isMounted: () => true,
    projects: () => [{ id: 1, slug: "demo", name: "Demo" }],
    client: { call: async () => ({ status: 200, envelope: { success: true,
      result: detail ? { method: { id: "command", name: "Command", plans: rows } } : { rows },
    } }) },
  };
  if (detail) await renderQaMethodDetail(context, host, ["1"], "command");
  else await renderQaPlans(context, host, ["1"]);
  return byClass(host, detail ? "qa-plan-link" : "qa-plan-button")
    .map((node) => detail ? node.children[0].children[0].textContent : node.textContent);
}

for (const detail of [false, true]) {
  test(`${detail ? "related" : "listed"} QA plans sort exact instants before name ties and nulls`, async () => {
    const clocks = [["a-earlier", first], ["n-missing", null],
      ["z-later", later], ["b-equal", equal],
      ["q-before-epoch", "1969-12-31T23:59:59.999999Z"]];
    const expected = ["z-later", "a-earlier", "b-equal", "q-before-epoch", "n-missing"];
    assert.deepEqual(await renderedPlanOrder(detail, clocks), expected);
    assert.deepEqual(await renderedPlanOrder(detail, [...clocks].reverse()), expected);
  });
  test(`${detail ? "related" : "listed"} QA plan ordering refuses unqualified clocks`, async () => {
    await assert.rejects(renderedPlanOrder(detail, [["valid", first],
      ["bad", "2060-10-08T00:00:00"]]), /invalid_instant/);
  });
}


import { planWindowHeadroom, readingIsStale } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_meters.js";
import { sessionHealthState } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_diagnostics.js";

test("an unexpired meter reset retains its last microsecond of runway", () => {
  const now = Date.parse("2060-10-08T00:00:00Z");
  const window = { status: "ok", window_kind: "rolling_5h", remaining_percent: 50 };
  for (const resets_at of ["2060-10-08T00:00:00.000001Z", "2060-10-08T05:45:00.000001+05:45"]) {
    assert.ok(planWindowHeadroom({ ...window, resets_at }, now) > 0);
  }
  for (const resets_at of ["2060-10-08T00:00:00.000000Z", "2060-10-07T23:59:59.999999Z", null]) {
    assert.equal(planWindowHeadroom({ ...window, resets_at }, now), null);
  }
});

test("an unqualified meter observation supplies no freshness", () => {
  const now = Date.parse("2060-10-08T00:00:00Z");
  assert.equal(readingIsStale("2060-10-08T00:00:00", now), true);
  assert.equal(readingIsStale("2060-10-08T00:00:00-00:00", now), true);
  assert.equal(readingIsStale("2060-10-08T00:00:00.000001Z", now), false);
});

test("session staleness is inclusive only after the exact eligible instant", () => {
  const now = Date.parse("2060-10-08T00:00:00Z");
  const row = { liveness: "active", claims: [{ target_kind: "item" }],
    stale_eligible_at: "2060-10-08T00:00:00.000001Z" };
  assert.equal(sessionHealthState(row, now), null);
  assert.equal(sessionHealthState({ ...row,
    stale_eligible_at: "2060-10-08T05:45:00.000001+05:45" }, now), null);
  assert.equal(sessionHealthState({ ...row,
    stale_eligible_at: "2060-10-08T00:00:00.000000Z" }, now).state, "possibly stale");
  assert.equal(sessionHealthState({ ...row, liveness: "stale" }, now).state, "stale");
});
