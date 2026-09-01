import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function item(target, title) {
  return {
    holding_kind: "work_claim",
    target_kind: "item",
    target,
    item_ref: target,
    item_project_id: 1,
    item_project_sequence: Number(target.split("-")[1]),
    item_title: title,
    item_status: "implementing",
    item_workflow_id: "dash",
  };
}

function card(documentNode, extras = {}) {
  return sessionCard(
    documentNode,
    {
      session_id: "session-1",
      liveness: "active",
      mode: extras.mode || "dash",
      executor: "codex",
      current_item: "YOK-20",
      current_item_project_id: 1,
      current_item_project_sequence: 20,
      current_item_title: "Current title",
      current_item_status: "implementing",
      current_item_workflow_id: "dash",
      activity_at: "2026-08-28T12:00:00Z",
      current_holdings_health: extras.health || "green",
      claims: [],
      holdings: extras.holdings || {
        current: [item("YOK-20", "Current title")],
        previous: [item("YOK-19", "Previous title")],
        previous_remainder: 0,
      },
      messageability: { messageable: false },
    },
    () => {},
  );
}

test("Previously held uses the same boxed structure as Steering, in grey", () => {
  const rendered = card(new FakeDocument());
  const previous = byClass(rendered, "session-holdings-previous")[0];
  const current = byClass(rendered, "session-holdings-current")[0];
  assert.equal(
    byClass(previous, "session-holdings-label")[0].textContent,
    "Previously held",
  );
  assert.equal(
    byClass(current, "session-holdings-label")[0].textContent,
    "Currently held",
  );
  assert.equal(byClass(previous, "session-lock").length, 1);
  assert.equal(byClass(previous, "session-item-link")[0].textContent, "YOK-19");
  assert.equal(byClass(previous, "session-item-title").length, 0);
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.css",
    import.meta.url,
  ), "utf8");
  const steering = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.css",
    import.meta.url,
  ), "utf8");
  assert.match(steering, /border-left: 3px solid var\(--yoke-accent\)/);
  assert.match(css, /border-left: 3px solid var\(--yoke-idle\)/);
  assert.match(css, /padding: 7px 9px/);
  assert.match(css, /border-radius: 4px/);
});

test("Currently held paints the server-projected health tone", () => {
  for (const health of ["green", "yellow", "orange", "red"]) {
    const rendered = card(new FakeDocument(), { health });
    const current = byClass(rendered, "session-holdings-current")[0];
    assert.equal(current.getAttribute("data-holdings-health"), health);
    assert.equal(
      byClass(current, "session-item-link")[0].textContent, "YOK-20",
    );
  }
});

test("Currently held does not derive health from activity timestamps", () => {
  const rendered = card(new FakeDocument(), { health: "orange" });
  const current = byClass(rendered, "session-holdings-current")[0];
  assert.equal(current.getAttribute("data-holdings-health"), "orange");
  assert.equal(byClass(rendered, "session-age").length, 1);
});

test("parked pill stays on the card while Currently held stays calm green", () => {
  const rendered = card(new FakeDocument(), {
    mode: "parked",
    health: "green",
  });
  const badge = byClass(rendered, "session-parked-badge")[0];
  assert.ok(!badge.className.includes("session-parked-badge-empty"));
  assert.equal(badge.hidden, false);
  assert.equal(
    byClass(rendered, "session-holdings-current")[0]
      .getAttribute("data-holdings-health"),
    "green",
  );
});
