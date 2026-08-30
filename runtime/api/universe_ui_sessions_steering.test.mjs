import assert from "node:assert/strict";
import test from "node:test";

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


function steeringMarkup(node) {
  return {
    lead: byClass(node, "session-steering-lead").length,
    context: byClass(node, "session-steering-context").length,
    report: byClass(node, "session-steering-report").length,
    group: byClass(node, "session-steering-group").length,
  };
}


test("holder cards show scope and omit it from the holdings list", () => {
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

  assert.equal(
    byClass(holder, "session-steering-lead-label")[0].textContent, "Steering",
  );
  assert.equal(byClass(holder, "session-steering-project")[0].textContent, "yoke");
  assert.equal(
    byClass(holder, "session-steering-docs")[0].textContent, "MISSION, VISION",
  );
  assert.equal(byClass(holder, "session-hold-target").length, 0);
  assert.deepEqual(steeringMarkup(holder), {
    lead: 1, context: 0, report: 0, group: 0,
  });
});


test("a non-steerer card does not render steering context or report custody", () => {
  const documentNode = new FakeDocument();
  const operator = card(documentNode, {
    ...baseRow("operator-1"),
    steering_coverage: {
      project: "yoke",
      holder_session_id: "holder-1",
    },
    steering_parent: { session_id: "holder-1", project: "yoke" },
    steering_report: {
      recipient_session_id: "holder-1",
      recipient_state: "pending",
      created_at: new Date().toISOString(),
    },
  });

  assert.deepEqual(steeringMarkup(operator), {
    lead: 0, context: 0, report: 0, group: 0,
  });
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
  assert.equal(
    byClass(holder, "session-steering-docs")[0].textContent, "no doc lock",
  );
});


test("a released seat and its document lock read as one previous row", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, {
    ...baseRow("previous-pair"),
    holdings: { current: [], previous: [
      {
        holding_kind: "work_claim", target_kind: "steering",
        target: "steering for project 3", project_id: 3,
        strategy_docs: ["CURRENT-PLAN"], released_at: "2026-08-29T12:00:00Z",
      },
      {
        holding_kind: "strategy_document", target_kind: "strategy_document",
        project_id: 3, strategy_doc: "CURRENT-PLAN",
        target: "platform · CURRENT-PLAN", released_at: "2026-08-29T12:00:00Z",
      },
    ], previous_remainder: 0 },
  }, [{ id: 3, slug: "platform" }]);

  // One seat, one row: the steering claim already names the document its
  // lock covers, so the lock folds into it instead of repeating it.
  assert.deepEqual(
    byClass(rendered, "session-hold-target").map((node) => node.textContent),
    ["platform · CURRENT-PLAN"],
  );
});


test("a previous document lock no released seat covers keeps its own row", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, {
    ...baseRow("previous-unpaired"),
    holdings: { current: [], previous: [
      {
        holding_kind: "work_claim", target_kind: "steering",
        target: "steering for project 3", project_id: 3,
        strategy_docs: ["CURRENT-PLAN"], released_at: "2026-08-29T12:00:00Z",
      },
      {
        holding_kind: "strategy_document", target_kind: "strategy_document",
        project_id: 3, strategy_doc: "MISSION",
        target: "platform · MISSION", released_at: "2026-08-29T12:00:00Z",
      },
    ], previous_remainder: 0 },
  }, [{ id: 3, slug: "platform" }]);

  // Somebody locked a document without taking the seat that steers from
  // it — no steering row states that hold, so it needs one of its own.
  assert.deepEqual(
    byClass(rendered, "session-hold-target").map((node) => node.textContent),
    ["platform · CURRENT-PLAN", "platform · MISSION"],
  );
});


test("same-named documents in two projects stay two previous rows", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, {
    ...baseRow("previous-two-projects"),
    holdings: { current: [], previous: [
      {
        holding_kind: "work_claim", target_kind: "steering",
        target: "steering for project 3", project_id: 3,
        strategy_docs: ["CURRENT-PLAN"], released_at: "2026-08-29T12:00:00Z",
      },
      {
        holding_kind: "strategy_document", target_kind: "strategy_document",
        project_id: 1, strategy_doc: "CURRENT-PLAN",
        target: "yoke · CURRENT-PLAN", released_at: "2026-08-29T12:00:00Z",
      },
    ], previous_remainder: 0 },
  }, [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);

  // The platform seat covers platform's CURRENT-PLAN and nothing else:
  // yoke's same-named document is a different lock and keeps its row.
  assert.deepEqual(
    byClass(rendered, "session-hold-target").map((node) => node.textContent),
    ["platform · CURRENT-PLAN", "yoke · CURRENT-PLAN"],
  );
});


test("a current document lock the steering block does not name keeps a row", () => {
  const documentNode = new FakeDocument();
  const holder = card(documentNode, {
    ...baseRow("holder-5"),
    holdings: { current: [
      {
        holding_kind: "work_claim",
        target_kind: "steering", project_id: 1, scope: { project_id: 1 },
        strategy_docs: ["MISSION"],
      },
      {
        holding_kind: "strategy_document", target_kind: "strategy_document",
        project_id: 1, strategy_doc: "MISSION", target: "yoke · MISSION",
      },
      {
        holding_kind: "strategy_document", target_kind: "strategy_document",
        project_id: 1, strategy_doc: "VISION", target: "yoke · VISION",
      },
    ], previous: [], previous_remainder: 0 },
  }, [{ id: 1, slug: "yoke" }]);

  // The steering line states MISSION, so its lock folds in; VISION is a
  // document held without a seat steering from it and still needs a row.
  assert.equal(
    byClass(holder, "session-steering-docs")[0].textContent, "MISSION",
  );
  assert.deepEqual(
    byClass(holder, "session-hold-target").map((node) => node.textContent),
    ["yoke · VISION"],
  );
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
