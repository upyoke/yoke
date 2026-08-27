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


function card(documentNode, row) {
  return sessionCard(documentNode, row, WHO, "hosted", () => {});
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
