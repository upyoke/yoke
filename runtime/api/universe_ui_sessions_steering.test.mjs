import assert from "node:assert/strict";
import test from "node:test";

import {
  appendSteeringGroups,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.js";
import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


const WHO = { label: "member", value: () => "Ben" };


function baseRow(sessionId) {
  return {
    session_id: sessionId,
    liveness: "active",
    mode: "wait",
    executor: "codex",
    claims: [],
    coordination_leases: [],
    activity_at: "2026-08-26T12:00:00Z",
    messageability: { messageable: false },
  };
}


function card(documentNode, row, projects = []) {
  return sessionCard(documentNode, row, WHO, "hosted", () => {}, projects);
}


test("holder and covered operator cards show scope and report custody", () => {
  const documentNode = new FakeDocument();
  const holder = card(documentNode, {
    ...baseRow("holder-1"),
    steering_scope: {
      project: "yoke",
      strategy_docs: ["MISSION", "VISION"],
    },
  });
  const operator = card(documentNode, {
    ...baseRow("operator-1"),
    steering_coverage: {
      project: "yoke",
      holder_session_id: "holder-1",
    },
    steering_report: {
      recipient_session_id: "holder-1",
      recipient_state: "pending",
      created_at: new Date().toISOString(),
    },
  });

  assert.equal(byClass(holder, "session-steering-badge")[0].textContent, "Steering");
  assert.equal(
    byClass(holder, "session-steering-detail")[0].textContent,
    "yoke · MISSION, VISION",
  );
  assert.equal(
    byClass(operator, "session-steering-detail")[0].textContent,
    "yoke · held by holder-1",
  );
  assert.match(
    byClass(operator, "session-steering-report-badge")[0].textContent,
    /^sent · /,
  );
});


test("steering states itself once however many projects it covers", () => {
  const documentNode = new FakeDocument();
  const holder = card(documentNode, {
    ...baseRow("holder-2"),
    claims: [
      {
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["CURRENT-PLAN"],
      },
      {
        target_kind: "steering", project_id: 3, scope: { project_id: 3 },
        strategy_docs: ["CURRENT-PLAN"],
      },
    ],
    steering_scope: { project: "yoke", strategy_docs: ["CURRENT-PLAN"] },
  }, [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);

  // One line for the whole of steering: the lock row per project and the
  // separate context badge said the same thing three times over. Both
  // projects still read as two holds even though their documents share a
  // slug, because each project is paired with its own.
  assert.equal(byClass(holder, "session-steering-context").length, 1);
  assert.equal(byClass(holder, "session-work").length, 1);
  assert.equal(
    byClass(holder, "session-steering-detail")[0].textContent,
    "yoke · CURRENT-PLAN; platform · CURRENT-PLAN",
  );
  assert.equal(byClass(holder, "session-hold-target").length, 0);
});


test("each steered project carries the documents it is steered from", () => {
  const documentNode = new FakeDocument();
  const holder = card(documentNode, {
    ...baseRow("holder-4"),
    claims: [
      {
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["MISSION", "VISION"],
      },
      {
        target_kind: "steering", project_id: 3, scope: { project_id: 3 },
        strategy_docs: ["MASTER-PLAN"],
      },
    ],
    steering_scope: { project: "yoke", strategy_docs: ["MISSION", "VISION"] },
  }, [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);

  // Semicolons separate projects, commas separate one project's documents,
  // so the platform hold cannot be read as a third yoke document.
  assert.equal(
    byClass(holder, "session-steering-detail")[0].textContent,
    "yoke · MISSION, VISION; platform · MASTER-PLAN",
  );
});


test("a steering claim alone still marks the session as steering", () => {
  const documentNode = new FakeDocument();
  // The scope projection describes the session's own project binding, so a
  // session steering only some other project has a claim and no scope row.
  const holder = card(documentNode, {
    ...baseRow("holder-3"),
    claims: [
      { target_kind: "steering", project_id: 3, scope: { project_id: 3 } },
    ],
  }, [{ id: 3, slug: "platform" }]);

  assert.equal(byClass(holder, "session-steering-badge")[0].textContent, "Steering");
  assert.equal(
    byClass(holder, "session-steering-detail")[0].textContent,
    "platform · all docs",
  );
});


test("acknowledged recipient state advances report custody", () => {
  const documentNode = new FakeDocument();
  const operator = card(documentNode, {
    ...baseRow("operator-1"),
    steering_report: {
      recipient_session_id: "holder-1",
      recipient_state: "acknowledged",
      created_at: "2026-08-26T12:00:00Z",
      acknowledged_at: new Date().toISOString(),
    },
  });

  assert.match(
    byClass(operator, "session-steering-report-badge")[0].textContent,
    /^acknowledged · /,
  );
});


test("steering-launched workers nest under their visible holder", () => {
  const documentNode = new FakeDocument();
  const holder = {
    ...baseRow("holder-1"),
    steering_scope: { project: "yoke", strategy_docs: [] },
  };
  const worker = {
    ...baseRow("worker-1"),
    steering_parent: { session_id: "holder-1", project: "yoke" },
  };
  const independent = baseRow("independent-1");
  const grid = documentNode.createElement("div");

  appendSteeringGroups(documentNode, grid, [holder, worker, independent], (row) => {
    const node = documentNode.createElement("article");
    node.className = "test-session-card";
    node.textContent = row.session_id;
    return node;
  });

  const group = byClass(grid, "session-steering-group")[0];
  assert.equal(group.getAttribute("data-steering-holder"), "holder-1");
  assert.equal(byClass(group, "session-steering-workers-title")[0].textContent, "Steering workers (1)");
  assert.equal(byClass(group, "session-steering-worker-grid")[0].textContent, "worker-1");
  assert.equal(grid.children[1].textContent, "independent-1");
});
