import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const ITEM_SEQUENCE = 20;
const ITEM_REF = `YOK-${ITEM_SEQUENCE}`;

function card({ frozen = false, blocked = false, mode = "dash", attached = false } = {}) {
  const holding = {
    holding_kind: "work_claim", target_kind: "item", target: ITEM_REF,
    item_frozen: frozen, item_blocked: blocked,
    item_blocked_reason: "waiting for review",
  };
  return sessionCard(new FakeDocument(), {
    session_id: "session", liveness: "active", mode, executor: "codex",
    current_item: ITEM_REF, current_item_project_id: 1,
    current_item_project_sequence: ITEM_SEQUENCE, current_item_title: "Work",
    current_item_status: "implementing", current_item_workflow_id: "dash",
    current_item_frozen: frozen, current_item_blocked: blocked,
    current_item_blocked_reason: "waiting for review",
    work_role: attached ? "engineer" : null,
    primary_item_stages: [
      { name: "idea", state: "complete" },
      { name: "implementing", state: "active" },
      { name: "done", state: "pending" },
    ],
    claims: [], holdings: {
      current: attached ? [] : [holding], previous: [], previous_remainder: 0,
    },
    messageability: { messageable: false },
  }, () => {});
}

test("normal, frozen, and blocked items render distinct conditions", () => {
  for (const [options, labels, stageTone] of [
    [{}, [], null],
    [{ frozen: true }, ["Frozen"], "frozen"],
    [{ blocked: true }, ["Blocked"], "blocked"],
    [{ frozen: true, blocked: true }, ["Frozen", "Blocked"], "frozen"],
  ]) {
    const rendered = card(options);
    assert.deepEqual(
      byClass(rendered, "session-item-condition").map((node) => node.textContent),
      labels,
    );
    const segments = byClass(rendered, "delivery-run-stage");
    assert.deepEqual(segments.map((node) => node.getAttribute("data-state")),
      ["complete", "active", "pending"]);
    assert.equal(segments[0].getAttribute("data-item-condition"), null);
    assert.equal(segments[1].getAttribute("data-item-condition"), stageTone);
    assert.equal(segments[2].getAttribute("data-item-condition"), null);
  }
});

test("parked and lane attached sessions use the item flags", () => {
  const rendered = card({ blocked: true, mode: "parked", attached: true });
  assert.equal(byClass(rendered, "session-item-condition")[0].textContent, "Blocked");
  assert.equal(
    byClass(rendered, "delivery-run-stage")[1].getAttribute("data-item-condition"),
    "blocked",
  );
});

test("current stage colors pulse in the shared desktop and mobile card markup", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.css",
    import.meta.url,
  ), "utf8");
  for (const tone of ["frozen", "blocked"]) {
    assert.match(css, new RegExp(`data-item-condition="${tone}"\\][\\s\\S]*?animation: delivery-run-pulse`));
  }
});
