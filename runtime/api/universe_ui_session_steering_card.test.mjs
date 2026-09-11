import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  createSteeringGroupColorAssigner,
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
  const groupColors = createSteeringGroupColorAssigner()(rows);
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
});

test("a shared assigner keeps a group's color the same across every page's own rows", () => {
  // Overview, Sessions, and a filtered project view each fetch their own
  // rows independently. mountUniverseApp hands every view the SAME
  // assigner (one per mounted app, via context.steeringGroupColors), so a
  // group's rank is decided once — the first time any page observes it —
  // and every later call reads that decision back rather than recomputing
  // it from its own local rows. Simulate that here with one assigner
  // standing in for the shared instance, called once per "page".
  const assigner = createSteeringGroupColorAssigner();
  const solo = assigner([steeringSeatRow("seat-solo")]).get("seat-solo");
  // A later "page" that also happens to know about an unrelated group
  // must not change a color already decided.
  const withUnrelatedCompany = assigner([
    steeringSeatRow("seat-elsewhere"),
  ]).get("seat-solo");
  assert.equal(solo, withUnrelatedCompany);

  // These two real steering-group ids hash to the exact same primary rank
  // (the reported production collision) — a per-render rank/bump, or a
  // per-id hash with no shared record, either recolors this pair
  // depending on whether both happen to be visible together or a
  // per-render rank reassigns everyone once a "page" sees more groups.
  // Seeing them on separate "pages" (one row each, never together) must
  // still land them on different colors, and each color must then hold
  // when a later "page" sees them together.
  const seatCurrentPlan = "01a088ce-8449-7101-91ae-1170b3312631";
  const seatReleases = "01a09089-a901-77e2-b41f-b3606e124b9e";
  const currentPlanAlone = assigner([steeringSeatRow(seatCurrentPlan)])
    .get(seatCurrentPlan);
  const releasesAlone = assigner([steeringSeatRow(seatReleases)])
    .get(seatReleases);
  assert.notEqual(currentPlanAlone, releasesAlone);
  const together = assigner([
    steeringSeatRow(seatCurrentPlan), steeringSeatRow(seatReleases),
  ]);
  assert.equal(together.get(seatCurrentPlan), currentPlanAlone);
  assert.equal(together.get(seatReleases), releasesAlone);
});

test("more than six concurrent groups stay pairwise distinct", () => {
  const ids = Array.from({ length: 8 }, (_, index) => `group-${index}`);
  const rows = ids.map((id) => steeringSeatRow(id));
  const groupColors = createSteeringGroupColorAssigner()(rows);
  const colors = ids.map((id) => groupColors.get(id));
  assert.equal(new Set(colors).size, colors.length);
  // Every color is either a fixed palette entry or a minted extra hue —
  // which specific ids land on which depends on discovery order, not
  // sorted position, so assert the format rather than a fixed mapping.
  for (const color of colors) {
    assert.ok(
      /^#[0-9a-f]{6}$/.test(color) || /^hsl\(/.test(color),
      `unexpected color format: ${color}`,
    );
  }
});
