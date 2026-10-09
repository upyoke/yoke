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
