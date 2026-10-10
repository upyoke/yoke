import assert from "node:assert/strict";
import test from "node:test";
import { strategyDocumentCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_strategy_cards.js";
import { renderQaPlans } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_plans.js";
import { renderQaMethodDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_methods.js";
import { relativeTimeNode } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_primitives.js";
import { formatInstant } from "../../packages/yoke-core/src/yoke_core/ui/static/timestamps.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const NOW = Date.parse("1970-02-02T00:00:00Z");
const PROJECT = { id: 1, slug: "yoke", name: "Yoke", public_item_prefix: "YOK" };

for (const [days, before, at] of [[1, "today", "week"], [7, "week", "month"], [30, "month", "old"]]) {
  test(`strategy freshness preserves microseconds at ${days} days`, (t) => {
    t.mock.method(Date, "now", () => NOW);
    const exact = formatInstant(new Date(NOW - days * 86400000).toISOString());
    for (const [stamp, tone] of [[exact.replace(".000000Z", ".000001Z"), before], [exact, at]]) {
      const doc = { slug: "MISSION", updated_at: stamp };
      const card = strategyDocumentCard(new FakeDocument(), doc, PROJECT);
      assert.ok(byClass(card, "strategy-doc-age")[0].classList.contains(`is-${tone}`));
      assert.equal(doc.updated_at, stamp);
    }
  });
}

test("absent or ambiguous strategy observations cannot establish freshness", (t) => {
  t.mock.method(Date, "now", () => NOW);
  for (const stamp of [null, "1970-02-01", "1970-02-01T00:00:00", "1970-02-01T00:00:00-00:00"]) {
    const card = strategyDocumentCard(new FakeDocument(), { slug: "MISSION", updated_at: stamp }, PROJECT);
    assert.ok(byClass(card, "strategy-doc-age")[0].classList.contains("is-unknown"));
  }
});

async function qaAge(render, stamp) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const plan = { id: 1, slug: "readiness", name: "Readiness", project: "yoke",
    case_keys: ["suite"], case_count: 1, method_ids: ["command"],
    method_is_complete_plan: true, last_outcome: "passed", last_at: stamp,
    outcome_summary: { state: "passed", counts: { passed: 1 }, last_at: stamp } };
  const context = { document, projects: () => [PROJECT], isMounted: () => true,
    client: { async call() { return { status: 200, envelope: { success: true, result: {
      rows: [plan], method: { id: "command", name: "Command", plans: [plan],
        required_capability_kinds: [], required_capabilities: [] },
    } } }; } } };
  await render(context, main, ["1"], "command");
  assert.equal(plan.last_at, stamp);
  return byClass(main, "qa-relative-time")[0];
}

for (const [name, render, suffix] of [["plans", renderQaPlans, ""], ["method plans", renderQaMethodDetail, " ago"]]) {
  test(`${name} yesterday bucket preserves both microsecond boundaries`, async (t) => {
    t.mock.method(Date, "now", () => NOW);
    for (const [seconds, younger, expected] of [[86400, true, `23h${suffix}`], [86400, false, "yesterday"], [172800, true, "yesterday"], [172800, false, `2d${suffix}`]]) {
      const exact = formatInstant(new Date(NOW - seconds * 1000).toISOString());
      const stamp = younger ? exact.replace(".000000Z", ".000001Z") : exact;
      const age = await qaAge(render, stamp);
      assert.equal(age.textContent, expected);
      assert.equal(age.dateTime, stamp);
    }
  });
}

for (const stamp of ["1969-12-31T23:59:00.000001Z", "1969-12-31T18:59:00.000001-05:00", "1970-01-01T05:44:00.000001+05:45"]) {
  test(`QA HTML clock canonicalizes qualified source ${stamp}`, (t) => {
    t.mock.method(Date, "now", () => 0);
    const time = relativeTimeNode(new FakeDocument(), stamp);
    assert.equal(time.dateTime, "1969-12-31T23:59:00.000001Z");
    assert.equal(time.getAttribute("data-tooltip"), time.dateTime);
    assert.equal(time.textContent, "now");
  });
}

test("QA HTML owner permits null and refuses ambiguous supplied clocks", () => {
  assert.equal(relativeTimeNode(new FakeDocument(), null).textContent, "—");
  for (const value of ["", "1970-01-01", "1970-01-01T00:00:00", "1970-01-01T00:00:00-00:00"]) {
    assert.throws(() => relativeTimeNode(new FakeDocument(), value), /invalid_instant/);
  }
});
