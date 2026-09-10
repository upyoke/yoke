import assert from "node:assert/strict";
import test from "node:test";

import { rowsInOverviewScope } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_primitives.js";

const PROJECTS = [{ id: 1, slug: "yoke" }, { id: 2, slug: "platform" }, { id: 3, slug: "third" }];

function homeSession(sessionId, projectId) {
  return {
    session_id: sessionId,
    project_id: projectId,
    liveness: "active",
    holdings: { current: [], previous: [], previous_remainder: 0 },
  };
}

function steeringSession(sessionId, homeProjectId, steeredProjectId, { released = false } = {}) {
  const claim = {
    holding_kind: "work_claim",
    target_kind: "steering",
    project_id: steeredProjectId,
    scope: { project_id: steeredProjectId },
  };
  return {
    session_id: sessionId,
    project_id: homeProjectId,
    liveness: "active",
    holdings: released
      ? { current: [], previous: [claim], previous_remainder: 0 }
      : { current: [claim], previous: [], previous_remainder: 0 },
  };
}

// Home-project-A session actively steering B: B's scope must still surface it.
test("a session steering a project other than its home project is in that project's scope", () => {
  const rows = [homeSession("s-yoke", 1), steeringSession("s-root", 1, 2)];
  assert.deepEqual(
    rowsInOverviewScope(rows, ["2"], PROJECTS).map((row) => row.session_id),
    ["s-root"],
  );
});

// A/B combined selection keeps both the home worker and the cross-project steerer.
test("a combined A/B scope keeps the home-project worker and the cross-project steerer", () => {
  const rows = [homeSession("s-yoke", 1), steeringSession("s-root", 1, 2)];
  assert.deepEqual(
    rowsInOverviewScope(rows, ["1", "2"], PROJECTS).map((row) => row.session_id).sort(),
    ["s-root", "s-yoke"],
  );
});

// A released scope must not add visibility — only current holdings count.
test("a released steering claim does not widen the session's scope", () => {
  const rows = [steeringSession("s-root", 1, 2, { released: true })];
  assert.deepEqual(rowsInOverviewScope(rows, ["2"], PROJECTS), []);
});

// An unrelated project must not gain visibility from a claim scoped elsewhere.
test("an unrelated project's scope does not include a session steering a different one", () => {
  const rows = [steeringSession("s-root", 1, 2)];
  assert.deepEqual(rowsInOverviewScope(rows, ["3"], PROJECTS), []);
});

// Item rows carry no holdings at all; the added predicate must stay inert
// rather than throwing or granting scope membership it never earned.
test("an item row with no holdings still filters on project alone", () => {
  const items = [
    { public_ref: "YOK-1", project_id: 1 },
    { public_ref: "BET-1", project_id: 2 },
  ];
  assert.deepEqual(
    rowsInOverviewScope(items, ["2"], PROJECTS).map((row) => row.public_ref),
    ["BET-1"],
  );
});
