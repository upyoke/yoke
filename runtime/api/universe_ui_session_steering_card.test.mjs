import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

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

test("a live steering seat paints the lavender card sheet", () => {
  const rendered = card(new FakeDocument(), { current: [steering] });
  assert.equal(rendered.getAttribute("data-steering-history"), "");
});

test("a released steering seat still paints the lavender card sheet", () => {
  const rendered = card(new FakeDocument(), {
    previous: [{ ...steering, released_at: "2026-08-26T12:00:00Z" }],
  });
  assert.equal(rendered.getAttribute("data-steering-history"), "");
});

test("an ordinary worker card does not wear the steering sheet", () => {
  const rendered = card(new FakeDocument(), {
    current: [{
      holding_kind: "work_claim", target_kind: "item", target: "YOK-20",
    }],
  });
  assert.equal(rendered.getAttribute("data-steering-history"), null);
});

test("a truncated previous list still paints when the model stamps steered", () => {
  const rendered = card(new FakeDocument(), { steered: true });
  assert.equal(rendered.getAttribute("data-steering-history"), "");
});

test("the steering sheet is a card tint; the lead box stays blue", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-card\[data-steering-history\] \{[\s\S]*#7c5cbf/,
  );
  assert.match(css, /border-left: 3px solid var\(--yoke-accent\)/);
});
