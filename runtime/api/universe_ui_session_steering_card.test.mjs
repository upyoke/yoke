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

function card(documentNode, holdings) {
  return sessionCard(
    documentNode,
    {
      session_id: "session-1",
      liveness: "active",
      mode: "dash",
      executor: "codex",
      claims: [],
      holdings: {
        current: [],
        previous: [],
        previous_remainder: 0,
        ...holdings,
      },
      messageability: { messageable: false },
    },
    () => {},
    [{ id: 1, slug: "yoke" }],
  );
}

const steering = {
  holding_kind: "work_claim",
  target_kind: "steering",
  project_id: 1,
  scope: { project_id: 1 },
  strategy_docs: ["CURRENT-PLAN"],
};

test("a live seat leads with the Steering box and a corner wheel", () => {
  const rendered = card(new FakeDocument(), { current: [steering] });
  const lead = byClass(rendered, "session-steering-lead")[0];
  const wheel = byClass(lead, "session-steering-wheel")[0];
  assert.equal(wheel.textContent, "🛞");
  assert.equal(
    wheel.title, "steering seat — this session steered this project",
  );
  assert.equal(
    wheel.getAttribute("aria-label"),
    "steering seat — this session steered this project",
  );
  // The wheel leads the box so it lands in the corner, not inline with
  // the label the operator reads first.
  assert.equal(lead.children[0], wheel);
  assert.equal(
    byClass(lead, "session-steering-lead-label")[0].textContent, "Steering",
  );
});


test("a released seat keeps no Steering box, so no wheel with it", () => {
  const rendered = card(new FakeDocument(), {
    previous: [{ ...steering, released_at: "2026-08-26T12:00:00Z" }],
  });
  assert.equal(byClass(rendered, "session-steering-lead").length, 0);
  assert.equal(byClass(rendered, "session-steering-wheel").length, 0);
});


test("an ordinary worker card carries no steering box", () => {
  const rendered = card(new FakeDocument(), {
    current: [{
      holding_kind: "work_claim", target_kind: "item", target: "YOK-20",
    }],
  });
  assert.equal(byClass(rendered, "session-steering-lead").length, 0);
});


test("a steering card wears no sheet of its own", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.css",
    import.meta.url,
  ), "utf8");
  // The card background is every other card's; the Steering box is what
  // differentiates the seat.
  assert.ok(!css.includes(".session-card"), "no card-level steering sheet");
  assert.match(css, /border-left: 3px solid var\(--yoke-accent\)/);
  assert.match(
    css, /\.session-steering-wheel \{[\s\S]*?position: absolute/,
  );
});
