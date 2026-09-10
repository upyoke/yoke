import assert from "node:assert/strict";
import test from "node:test";

import { sortSessionsSteeringFirst } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.js";

function workerRow(sessionId) {
  return {
    session_id: sessionId,
    liveness: "active",
    holdings: { current: [], previous: [], previous_remainder: 0 },
  };
}

function steeringRow(sessionId, projectId = 1) {
  return {
    session_id: sessionId,
    liveness: "active",
    holdings: { current: [
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: projectId,
        scope: { project_id: projectId },
        strategy_docs: ["MISSION"],
      },
    ], previous: [], previous_remainder: 0 },
  };
}

// A session that used to steer but released the seat has no current
// steering holding left, only released history — it must not be treated as
// still steering.
function releasedSteeringRow(sessionId) {
  return {
    session_id: sessionId,
    liveness: "ended",
    holdings: { current: [], previous: [
      { holding_kind: "work_claim", target_kind: "steering", project_id: 1 },
    ], previous_remainder: 0 },
  };
}

test("a single active steering session moves ahead of ordinary workers", () => {
  const ordered = sortSessionsSteeringFirst([
    workerRow("worker-1"),
    workerRow("worker-2"),
    steeringRow("steer-1"),
  ]);
  assert.deepEqual(
    ordered.map((row) => row.session_id),
    ["steer-1", "worker-1", "worker-2"],
  );
});

test("multiple active steering sessions stay ahead of workers, each group in its incoming order", () => {
  const ordered = sortSessionsSteeringFirst([
    workerRow("worker-1"),
    steeringRow("steer-1"),
    workerRow("worker-2"),
    steeringRow("steer-2"),
  ]);
  assert.deepEqual(
    ordered.map((row) => row.session_id),
    ["steer-1", "steer-2", "worker-1", "worker-2"],
  );
});

test("a released steering hold does not count as active steering", () => {
  const ordered = sortSessionsSteeringFirst([
    workerRow("worker-1"),
    releasedSteeringRow("ended-steer"),
    steeringRow("steer-1"),
  ]);
  assert.deepEqual(
    ordered.map((row) => row.session_id),
    ["steer-1", "worker-1", "ended-steer"],
  );
});

test("ordinary ordering is unchanged when no session is steering", () => {
  const rows = [workerRow("worker-1"), workerRow("worker-2"), workerRow("worker-3")];
  assert.deepEqual(
    sortSessionsSteeringFirst(rows).map((row) => row.session_id),
    ["worker-1", "worker-2", "worker-3"],
  );
});

test("input array is not mutated", () => {
  const rows = [workerRow("worker-1"), steeringRow("steer-1")];
  const snapshot = rows.map((row) => row.session_id);
  sortSessionsSteeringFirst(rows);
  assert.deepEqual(rows.map((row) => row.session_id), snapshot);
});
