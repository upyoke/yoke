import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  steeringGroupColors,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.js";
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

test("a live seat leads with the Steering box and designed corner symbol", () => {
  const rendered = card(new FakeDocument(), { current: [steering] });
  const lead = byClass(rendered, "session-steering-lead")[0];
  const symbol = byClass(lead, "session-steering-symbol")[0];
  assert.equal(symbol.textContent, "");
  const svg = symbol.children[0];
  assert.equal(svg.tagName, "SVG");
  assert.equal(svg.getAttribute("viewBox"), "0 0 209.8 142");
  assert.equal(svg.children[0].getAttribute("fill"), "currentColor");
  assert.equal(svg.children[1].getAttribute("stroke"), "currentColor");
  assert.equal(
    symbol.getAttribute("data-tooltip"),
    "steering seat — this session steered this project",
  );
  assert.equal(symbol.getAttribute("aria-hidden"), "true");
  assert.equal(symbol.getAttribute("aria-label"), null);
  // The symbol leads the box so it lands in the corner, not inline with
  // the label the operator reads first.
  assert.equal(lead.children[0], symbol);
  assert.equal(
    byClass(lead, "session-steering-lead-label")[0].textContent, "Steering",
  );
  assert.equal(
    byClass(lead, "session-steering-wide")[0].textContent, "Project-wide",
  );
  assert.equal(byClass(lead, "session-steering-docs").length, 0);
});


test("a released seat keeps no Steering box or corner symbol", () => {
  const rendered = card(new FakeDocument(), {
    previous: [{ ...steering, released_at: "2026-08-26T12:00:00Z" }],
  });
  assert.equal(byClass(rendered, "session-steering-lead").length, 0);
  assert.equal(byClass(rendered, "session-steering-symbol").length, 0);
});


test("an ordinary worker card carries no steering box", () => {
  const rendered = card(new FakeDocument(), {
    current: [{
      holding_kind: "work_claim", target_kind: "item", target: "YOK-20",
    }],
  });
  assert.equal(byClass(rendered, "session-steering-lead").length, 0);
});


test("associated cards share the steering seat tint", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-card\.is-steering-associated \{[\s\S]*?color-mix/,
  );
  assert.doesNotMatch(
    css,
    /\.session-card\.is-steering-associated\.is-stale/,
  );
  assert.match(
    css,
    /border-left: 3px solid var\(--session-steering-color, var\(--yoke-accent\)\)/,
  );
  assert.match(
    css, /\.session-steering-symbol \{[\s\S]*?position: absolute/,
  );
  assert.match(css, /\.steering-symbol svg \{[\s\S]*?height: 14px/);
  assert.match(css, /\.steering-symbol svg \{[\s\S]*?width: auto/);
});


test("coverage association tints the outer card", () => {
  const rendered = sessionCard(
    new FakeDocument(),
    {
      session_id: "worker-1",
      liveness: "active",
      mode: "dash",
      executor: "codex",
      claims: [],
      holdings: { current: [], previous: [], previous_remainder: 0 },
      messageability: { messageable: false },
      steering_group_session_id: "seat-1",
    },
    () => {},
    [{ id: 1, slug: "yoke" }],
  );
  assert.ok(rendered.classList.contains("is-steering-associated"));
  assert.equal(rendered.getAttribute("data-steering-group"), "seat-1");
});


test("a stale associated card keeps its group tint class alongside the stale class", () => {
  const rendered = sessionCard(
    new FakeDocument(),
    {
      session_id: "worker-1",
      liveness: "stale",
      mode: "dash",
      executor: "codex",
      claims: [],
      holdings: { current: [], previous: [], previous_remainder: 0 },
      messageability: { messageable: false },
      steering_group_session_id: "seat-1",
    },
    () => {},
    [{ id: 1, slug: "yoke" }],
  );
  assert.ok(rendered.classList.contains("is-steering-associated"));
  assert.ok(rendered.classList.contains("is-stale"));
});


function steeringWorkerRow(sessionId, groupSessionId) {
  return {
    session_id: sessionId,
    liveness: "active",
    holdings: { current: [], previous: [], previous_remainder: 0 },
    messageability: { messageable: false },
    steering_group_session_id: groupSessionId,
  };
}

function steeringSeatRow(sessionId) {
  return {
    session_id: sessionId,
    liveness: "active",
    holdings: { current: [steering], previous: [], previous_remainder: 0 },
    messageability: { messageable: false },
    steering_group_session_id: sessionId,
  };
}

test("each steering group renders its own color, shared with its workers", () => {
  const rows = [
    steeringSeatRow("seat-1"),
    steeringWorkerRow("worker-1", "seat-1"),
    steeringSeatRow("seat-2"),
  ];
  const groupColors = steeringGroupColors(rows);
  const cardFor = (row) => sessionCard(
    new FakeDocument(), row, () => {}, [{ id: 1, slug: "yoke" }], groupColors,
  );
  const seatOne = cardFor(rows[0]);
  const workerOfSeatOne = cardFor(rows[1]);
  const seatTwo = cardFor(rows[2]);
  const colorOne = seatOne.style.getPropertyValue("--session-steering-color");
  const colorTwo = seatTwo.style.getPropertyValue("--session-steering-color");
  assert.notEqual(colorOne, colorTwo);
  // The covered worker's card carries the SAME group color as its seat —
  // one visual group, one custom-property value — not a separately
  // computed one.
  assert.equal(
    workerOfSeatOne.style.getPropertyValue("--session-steering-color"),
    colorOne,
  );
  // Deterministic across renders: the same known row set always produces
  // the same map, with no registry and no render-order dependence.
  assert.deepEqual(
    [...steeringGroupColors(rows).entries()], [...groupColors.entries()],
  );
});

test("a group's color does not depend on which other groups the caller also knows about", () => {
  // Overview, Sessions, and a filtered project view each fetch their own
  // rows independently, so a group's color has to come from its own id,
  // never from its rank among whatever else a particular call also
  // happened to fetch — including a colliding sibling that is present in
  // one call's rows and absent (filtered out) from another's. This is the
  // exact regression a per-render rank/bump reintroduces: the shared id's
  // color must be identical whether or not its sibling is in the same row
  // set, not merely when the two are never rendered together. A row's shape
  // carries no "open" vs "history" distinction (see steeringSeatRow) — the
  // Sessions page's history-loaded rows are exactly this same subset case,
  // so this also covers a loaded-in ended-session card keeping its color.
  const solo = steeringGroupColors([steeringSeatRow("seat-solo")]).get("seat-solo");
  const withUnrelatedCompany = steeringGroupColors([
    steeringSeatRow("seat-solo"), steeringSeatRow("seat-elsewhere"),
  ]).get("seat-solo");
  assert.equal(solo, withUnrelatedCompany);

  // "seat-1" and "seat-2" land on adjacent ranks (see steeringGroupColors'
  // hash), so they are a real pair to check across subsets: rendered
  // together and rendered with one of the two absent must agree.
  const together = steeringGroupColors([
    steeringSeatRow("seat-1"), steeringSeatRow("seat-2"),
  ]);
  const seat1Alone = steeringGroupColors([steeringSeatRow("seat-1")]);
  const seat2Alone = steeringGroupColors([steeringSeatRow("seat-2")]);
  assert.equal(together.get("seat-1"), seat1Alone.get("seat-1"));
  assert.equal(together.get("seat-2"), seat2Alone.get("seat-2"));
});

test("more than six concurrent groups stay pairwise distinct", () => {
  const ids = Array.from({ length: 8 }, (_, index) => `group-${index}`);
  const rows = ids.map((id) => steeringSeatRow(id));
  const groupColors = steeringGroupColors(rows);
  const colors = ids.map((id) => groupColors.get(id));
  assert.equal(new Set(colors).size, colors.length);
  // Every color is either a fixed palette entry or a minted extra hue —
  // which specific ids land on which depends on each id's own hash, not
  // sorted position, so assert the format rather than a fixed mapping.
  for (const color of colors) {
    assert.ok(
      /^#[0-9a-f]{6}$/.test(color) || /^hsl\(/.test(color),
      `unexpected color format: ${color}`,
    );
  }
});
