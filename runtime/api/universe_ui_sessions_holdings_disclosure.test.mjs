import assert from "node:assert/strict";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { renderSessionRows } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_history_loader.js";
import {
  compactStrategyDocuments,
  CURRENT_HOLDINGS_LIMIT,
  PREVIOUS_HOLDINGS_LIMIT,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings_disclosure.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function item(target) {
  return {
    holding_kind: "work_claim",
    target_kind: "item",
    target,
    item_ref: target,
    item_project_id: 1,
    item_project_sequence: Number(String(target).split("-")[1]),
  };
}

function doc(projectId, slug, project = "yoke") {
  return {
    holding_kind: "strategy_document",
    target_kind: "strategy_document",
    project_id: projectId,
    strategy_doc: slug,
    target: `${project} · ${slug}`,
  };
}

function card(documentNode, extras = {}) {
  return sessionCard(
    documentNode,
    {
      session_id: extras.sessionId || "holdings-disclose-1",
      liveness: "active",
      mode: "dash",
      executor: "codex",
      current_item: extras.currentItem || null,
      activity_at: "2026-08-28T12:00:00Z",
      claims: [],
      holdings: extras.holdings,
      messageability: { messageable: false },
    },
    () => {},
    extras.projects || [
      { id: 1, slug: "yoke" },
      { id: 3, slug: "platform" },
    ],
  );
}

test("compactStrategyDocuments groups one project and keeps mixed projects apart", () => {
  const units = compactStrategyDocuments([
    doc(1, "MISSION"),
    doc(1, "VISION"),
    doc(3, "CURRENT-PLAN", "platform"),
    item("YOK-20"),
  ], [{ id: 1, slug: "yoke" }, { id: 3, slug: "platform" }]);
  assert.equal(units[0].kind, "documents");
  assert.equal(units[0].project, "yoke");
  assert.equal(units[0].entries.length, 2);
  assert.equal(units[1].kind, "row");
  assert.equal(units[1].entry.strategy_doc, "CURRENT-PLAN");
  assert.equal(units[2].kind, "row");
});

test("current and previous sections share one disclosure and keep 8/3 limits", () => {
  const current = Array.from({ length: CURRENT_HOLDINGS_LIMIT + 2 }, (_, i) => (
    item(`YOK-${200 + i}`)
  ));
  const previous = Array.from({ length: PREVIOUS_HOLDINGS_LIMIT + 1 }, (_, i) => (
    item(`YOK-${10 + i}`)
  ));
  const rendered = card(new FakeDocument(), {
    holdings: { current, previous, previous_remainder: 0 },
  });
  const currentBox = byClass(rendered, "session-holdings-current")[0];
  const previousBox = byClass(rendered, "session-holdings-previous")[0];
  const currentMore = byClass(currentBox, "session-holdings-more")[0];
  const previousMore = byClass(previousBox, "session-holdings-more")[0];
  assert.equal(currentMore.textContent, "and 2 more");
  assert.equal(previousMore.textContent, "and 1 more");
  assert.equal(currentMore.getAttribute("aria-expanded"), "false");
  assert.equal(previousMore.getAttribute("aria-expanded"), "false");
  assert.notEqual(
    currentMore.getAttribute("aria-controls"),
    previousMore.getAttribute("aria-controls"),
  );
  assert.equal(byClass(currentBox, "session-holdings-rest")[0].hidden, true);
  currentMore.dispatchEvent(new Event("click"));
  assert.equal(currentMore.getAttribute("aria-expanded"), "true");
  assert.equal(currentMore.textContent, "Show less");
  assert.equal(byClass(currentBox, "session-holdings-rest")[0].hidden, false);
  assert.equal(previousMore.getAttribute("aria-expanded"), "false");
});

function nineCurrent() {
  return {
    current: Array.from({ length: 9 }, (_, i) => item(`YOK-${300 + i}`)),
    previous: [],
    previous_remainder: 0,
  };
}

function paintRoster(documentNode, host, extras = {}) {
  const sessionId = extras.sessionId || "holdings-disclose-1";
  const holdings = extras.holdings || nineCurrent();
  const row = {
    session_id: sessionId,
    liveness: "active",
    mode: "dash",
    executor: "codex",
    activity_at: "2026-08-28T12:00:00Z",
    claims: [],
    holdings,
    messageability: { messageable: false },
  };
  renderSessionRows(
    documentNode,
    host,
    [row],
    () => card(documentNode, { holdings, sessionId, ...extras }),
  );
}

test("expansion survives a live roster refresh and restores focus after insertion", () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  documentNode.body.appendChild(host);
  const extras = { sessionId: "holdings-disclose-focus", holdings: nineCurrent() };
  paintRoster(documentNode, host, extras);
  const more = byClass(host, "session-holdings-more")[0];
  more.focus();
  more.dispatchEvent(new Event("click"));
  paintRoster(documentNode, host, extras);
  const again = byClass(host, "session-holdings-more")[0];
  assert.notEqual(again, more);
  assert.equal(again.getAttribute("aria-expanded"), "true");
  assert.equal(again.textContent, "Show less");
  assert.equal(byClass(host, "session-holdings-rest")[0].hidden, false);
  assert.equal(documentNode.activeElement, again);
});

test("a roster refresh does not steal focus moved elsewhere", () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const elsewhere = documentNode.createElement("button");
  documentNode.body.appendChild(host);
  documentNode.body.appendChild(elsewhere);
  const extras = { sessionId: "holdings-disclose-elsewhere", holdings: nineCurrent() };
  paintRoster(documentNode, host, extras);
  const more = byClass(host, "session-holdings-more")[0];
  more.focus();
  more.dispatchEvent(new Event("click"));
  elsewhere.focus();
  paintRoster(documentNode, host, extras);
  const again = byClass(host, "session-holdings-more")[0];
  assert.equal(again.getAttribute("aria-expanded"), "true");
  assert.equal(documentNode.activeElement, elsewhere);
});

test("building a replacement card does not focus before it is inserted", () => {
  const documentNode = new FakeDocument();
  const first = card(documentNode, {
    sessionId: "holdings-disclose-orphan",
    holdings: nineCurrent(),
  });
  const more = byClass(first, "session-holdings-more")[0];
  more.focus();
  more.dispatchEvent(new Event("click"));
  const replacement = card(documentNode, {
    sessionId: "holdings-disclose-orphan",
    holdings: nineCurrent(),
  });
  assert.equal(documentNode.activeElement, more);
  assert.equal(
    byClass(replacement, "session-holdings-more")[0].getAttribute("aria-expanded"),
    "true",
  );
});

test("independent session cards do not share expansion", () => {
  const holdings = {
    current: Array.from({ length: 9 }, (_, i) => item(`YOK-${400 + i}`)),
    previous: [],
    previous_remainder: 0,
  };
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  host.appendChild(card(documentNode, { holdings, sessionId: "card-a" }));
  host.appendChild(card(documentNode, { holdings, sessionId: "card-b" }));
  const buttons = byClass(host, "session-holdings-more");
  buttons[0].dispatchEvent(new Event("click"));
  assert.equal(buttons[0].getAttribute("aria-expanded"), "true");
  assert.equal(buttons[1].getAttribute("aria-expanded"), "false");
});

test("a counted document group names one project and discloses exact rows", () => {
  const rendered = card(new FakeDocument(), {
    holdings: {
      current: [doc(1, "MISSION"), doc(1, "VISION"), item("YOK-20")],
      previous: [],
      previous_remainder: 0,
    },
  });
  const toggle = byClass(rendered, "session-holdings-docs-toggle")[0];
  assert.equal(toggle.tagName, "BUTTON");
  assert.match(toggle.textContent, /yoke · 2 documents/);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  const region = byClass(rendered, "session-holdings-docs")[0];
  assert.equal(region.hidden, true);
  assert.deepEqual(
    byClass(region, "session-hold-target").map((node) => node.textContent),
    ["yoke · MISSION", "yoke · VISION"],
  );
  toggle.dispatchEvent(new Event("click"));
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(region.hidden, false);
  assert.ok(!toggle.textContent.includes("platform"));
});
