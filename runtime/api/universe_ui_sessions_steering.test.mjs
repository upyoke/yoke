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
    holdings: { current: [], previous: [], previous_remainder: 0 },
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
    holdings: { current: [
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["MISSION", "VISION"],
      },
      {
        holding_kind: "strategy_document", project_id: 1,
        strategy_doc: "MISSION", target: "yoke · MISSION",
      },
      {
        holding_kind: "strategy_document", project_id: 1,
        strategy_doc: "VISION", target: "yoke · VISION",
      },
    ], previous: [], previous_remainder: 0 },
  }, [{ id: 1, slug: "yoke" }]);
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

  assert.equal(
    byClass(holder, "session-steering-lead-label")[0].textContent, "Steering",
  );
  assert.equal(byClass(holder, "session-steering-project")[0].textContent, "yoke");
  assert.equal(
    byClass(holder, "session-steering-docs")[0].textContent, "MISSION, VISION",
  );
  // The block states the seat and both documents, so the holdings list below
  // does not repeat them.
  assert.equal(byClass(holder, "session-hold-target").length, 0);
  assert.equal(
    byClass(operator, "session-steering-detail")[0].textContent,
    "yoke · held by holder-1",
  );
  assert.equal(
    byClass(operator, "session-steering-badge")[0].textContent,
    "Steering coverage",
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
    holdings: { current: [
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["CURRENT-PLAN"],
      },
      {
        holding_kind: "strategy_document", project_id: 1,
        strategy_doc: "CURRENT-PLAN", target: "yoke · CURRENT-PLAN",
      },
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 3, scope: { project_id: 3 },
        strategy_docs: ["CURRENT-PLAN"],
      },
      {
        holding_kind: "strategy_document", project_id: 3,
        strategy_doc: "CURRENT-PLAN", target: "platform · CURRENT-PLAN",
      },
    ], previous: [], previous_remainder: 0 },
  }, [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);

  // Two seats and two document locks read as two projects, each beside its
  // own document, in one block — never as one project with two documents.
  assert.equal(byClass(holder, "session-steering-lead").length, 1);
  assert.deepEqual(
    byClass(holder, "session-steering-project").map((node) => node.textContent),
    ["yoke", "platform"],
  );
  assert.deepEqual(
    byClass(holder, "session-steering-docs").map((node) => node.textContent),
    ["CURRENT-PLAN", "CURRENT-PLAN"],
  );
  assert.equal(byClass(holder, "session-hold-target").length, 0);
});


test("each steered project carries the documents it is steered from", () => {
  const documentNode = new FakeDocument();
  const holder = card(documentNode, {
    ...baseRow("holder-4"),
    holdings: { current: [
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["MISSION", "VISION"],
      },
      {
        holding_kind: "strategy_document", project_id: 1,
        strategy_doc: "MISSION", target: "yoke · MISSION",
      },
      {
        holding_kind: "strategy_document", project_id: 1,
        strategy_doc: "VISION", target: "yoke · VISION",
      },
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 3, scope: { project_id: 3 },
        strategy_docs: ["MASTER-PLAN"],
      },
      {
        holding_kind: "strategy_document", project_id: 3,
        strategy_doc: "MASTER-PLAN", target: "platform · MASTER-PLAN",
      },
    ], previous: [], previous_remainder: 0 },
  }, [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);

  // Each project keeps its own documents, so the platform hold cannot be
  // read as a third yoke document.
  assert.deepEqual(
    byClass(holder, "session-steering-scope").map((node) => node.textContent),
    ["yokeMISSION, VISION", "platformMASTER-PLAN"],
  );
});


test("a steering claim alone still marks the session as steering", () => {
  const documentNode = new FakeDocument();
  // The scope projection describes the session's own project binding, so a
  // session steering only some other project has a claim and no scope row.
  const holder = card(documentNode, {
    ...baseRow("holder-3"),
    holdings: { current: [{
      holding_kind: "work_claim",
      target_kind: "steering", project_id: 3, scope: { project_id: 3 },
    }], previous: [], previous_remainder: 0 },
  }, [{ id: 3, slug: "platform" }]);

  assert.equal(
    byClass(holder, "session-steering-lead-label")[0].textContent, "Steering",
  );
  assert.equal(
    byClass(holder, "session-steering-project")[0].textContent, "platform",
  );
  assert.equal(byClass(holder, "session-steering-docs")[0].textContent, "all docs");
});


test("previous steering holdings use the paired project and document label", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, {
    ...baseRow("previous-holder"),
    holdings: { current: [], previous: [{
      holding_kind: "work_claim", target_kind: "steering",
      target: "steering for project 3", project_id: 3,
      strategy_docs: ["CURRENT-PLAN"], released_at: "2026-08-26T12:00:00Z",
    }], previous_remainder: 0 },
  }, [{ id: 3, slug: "platform" }]);

  assert.deepEqual(
    byClass(rendered, "session-hold-target").map((node) => node.textContent),
    ["platform · CURRENT-PLAN"],
  );
  assert.ok(!rendered.textContent.includes("project 3"));
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
    holdings: { current: [{
      holding_kind: "work_claim",
      target_kind: "steering", project_id: 1, scope: { project_id: 1 },
    }], previous: [], previous_remainder: 0 },
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


test("a worker whose holder is absent remains a top-level card", () => {
  const documentNode = new FakeDocument();
  const worker = {
    ...baseRow("worker-2"),
    steering_parent: { session_id: "missing-holder", project: "yoke" },
  };
  const grid = documentNode.createElement("div");

  appendSteeringGroups(documentNode, grid, [worker], (row) => {
    const node = documentNode.createElement("article");
    node.textContent = row.session_id;
    return node;
  });

  assert.equal(byClass(grid, "session-steering-group").length, 0);
  assert.equal(grid.textContent, "worker-2");
});
