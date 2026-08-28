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


function item(target, title) {
  return {
    holding_kind: "work_claim",
    target_kind: "item",
    target,
    item_ref: target,
    item_project_id: 1,
    item_project_sequence: Number(target.split("-")[1]),
    item_title: title,
    item_status: "done",
    item_workflow_id: "dash",
  };
}


function card(documentNode, liveness, holdings) {
  return sessionCard(
    documentNode,
    {
      session_id: `${liveness}-1`,
      liveness,
      mode: "wait",
      executor: "codex",
      current_item: "YOK-20",
      current_item_project_id: 1,
      current_item_project_sequence: 20,
      current_item_title: "Current title",
      current_item_status: "implementing",
      current_item_workflow_id: "dash",
      activity_at: "2026-08-28T12:00:00Z",
      claims: [],
      holdings,
      messageability: { messageable: false },
    },
    WHO,
    "hosted",
    () => {},
  );
}


test("web tile labels current and previous groups with one title each", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, "active", {
    current: [item("YOK-20", "Current title")],
    previous: [
      item("YOK-19", "Previous title"),
      { holding_kind: "coordination", target: "QA_HOST:test-mac" },
    ],
    previous_remainder: 2,
  });

  assert.deepEqual(
    byClass(rendered, "session-holdings-label").map((node) => node.textContent),
    ["Currently held", "Previously held"],
  );
  assert.deepEqual(
    byClass(rendered, "session-item-title").map((node) => node.textContent),
    ["Current title", "Previous title"],
  );
  assert.deepEqual(
    byClass(rendered, "session-holdings-more").map((node) => node.textContent),
    ["and 2 more"],
  );
  assert.equal(byClass(rendered, "session-item-stage").length, 0);
});


test("previous holdings render for active stale and ended sessions", () => {
  const documentNode = new FakeDocument();
  for (const liveness of ["active", "stale", "ended"]) {
    const rendered = card(documentNode, liveness, {
      current: [],
      previous: [item("YOK-19", "Previous title")],
      previous_remainder: 0,
    });
    assert.deepEqual(
      byClass(rendered, "session-holdings-label").map((node) => node.textContent),
      ["Previously held"],
    );
  }
});


test("ended tile suppresses idle and actionable-work lines", () => {
  const documentNode = new FakeDocument();
  const rendered = card(documentNode, "ended", {
    current: [], previous: [], previous_remainder: 0,
  });

  assert.equal(byClass(rendered, "session-age").length, 0);
  assert.equal(byClass(rendered, "session-attached").length, 0);
  assert.equal(byClass(rendered, "session-unassigned").length, 0);
});
