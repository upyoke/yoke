import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  ok,
  sessionsClient,
  visibleText,
} from "./universe_ui_sessions_view_test_support.mjs";

test("Sessions renders resolved local identity and the exact empty state", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  let rows = [{
    session_id: "local-1", liveness: "active",
    execution_lane: "DARIUS", mode: "charge",
    executor: "codex", model: "gpt-5.6-sol",
    executor_mark: "X", executor_class_name: "h-codex",
    actor_id: 2, actor_kind: "human", actor_label: "Ben",
    project_id: 1, project: "yoke", current_item: null,
    current_item_title: null, activity_at: "2026-07-26T12:00:00Z",
    claims: [],
  }];
  const client = sessionsClient(() => rows, []);
  const mounted = mountUniverseApp(root, {
    client,
    capabilities: { data: { portability: { mode: "local" } } },
  });
  await settle();

  assert.equal(byClass(root, "page-head")[0].hidden, true);
  const sections = byClass(root, "overview-section");
  assert.equal(sections.length, 2);
  assert.equal(sections.every((node) => node.tagName === "DETAILS"), true);
  assert.equal(sections.every(
    (node) => node.children[0].tagName === "SUMMARY",
  ), true);
  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Machines", "Sessions"],
  );
  assert.equal(byClass(root, "session-operator")[0].textContent, "Ben");
  assert.equal(byClass(root, "session-actor-avatar").length, 0);
  assert.ok(visibleText(root).includes("No active work claims"));
  mounted.unmount();

  const emptyDocument = new FakeDocument();
  emptyDocument.defaultView.location.hash = "#/sessions?project=1";
  const emptyRoot = emptyDocument.createElement("div");
  rows = [];
  const emptyMount = mountUniverseApp(emptyRoot, {
    client: sessionsClient(() => rows, []),
  });
  await settle();
  assert.equal(
    byClass(emptyRoot, "sessions-empty")[0].textContent,
    "No sessions match the current filters.",
  );
  assert.deepEqual(
    byClass(emptyRoot, "sessions-stats")[0].children.map(
      (tile) => tile.children[0].textContent,
    ),
    ["0", "0", "0"],
  );
  const filterHost = byClass(emptyRoot, "session-roster-filters")[0];
  assert.deepEqual(
    filterHost.children.map((node) => node.tagName),
    ["LABEL", "LABEL", "LABEL", "LABEL", "BUTTON", "SPAN"],
  );
  const filterControls = byClass(filterHost, "session-filter-control");
  assert.deepEqual(
    filterControls.map((control) => control.tagName),
    ["INPUT", "SELECT", "SELECT", "SELECT"],
  );
  assert.equal(
    filterControls[0].placeholder,
    "Search sessions, items, models, operators",
  );
  assert.deepEqual(
    byClass(filterHost, "session-filter-label").map((node) => node.textContent),
    ["State", "Harness", "Machine"],
  );
  const filterButtons = [
    byClass(filterHost, "session-filter-clear")[0],
    ...byClass(filterHost, "session-filter-action"),
  ];
  assert.deepEqual(
    filterButtons.map((button) => button.textContent),
    ["Clear", "Message all", "Reclaim stale"],
  );
  assert.equal(
    filterButtons.at(-1).className,
    "item-button session-filter-action",
  );
  assert.equal(filterButtons.at(-1).disabled, true);
  assert.equal(byClass(emptyRoot, "session-control-actions").length, 0);
  assert.equal(byClass(emptyRoot, "head-actions").length, 0);
  emptyMount.unmount();
});

test("session cards omit only absent or placeholder operator names", () => {
  const render = (actorLabel) => sessionCard(
    new FakeDocument(),
    {
      session_id: "operator-card",
      liveness: "active",
      executor: "codex",
      actor_id: 2,
      actor_kind: "human",
      actor_label: actorLabel,
      claims: [],
      messageability: { messageable: false },
    },
    () => {},
  );

  assert.equal(byClass(render("ben"), "session-operator")[0].textContent, "ben");
  for (const missing of [null, "", "—"]) {
    assert.equal(byClass(render(missing), "session-operator").length, 0);
  }
});

test("Sessions reports a scoped read failure without presenting cleanup as available", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const base = sessionsClient([], []);
  const client = {
    async call(request) {
      if (request.function === "sessions.list") {
        return {
          status: 503,
          envelope: {
            success: false,
            error: { message: "session registry unavailable" },
          },
        };
      }
      return base.call(request);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  // Two independent reads, two independent failures. The Machines panel above
  // reports its own, so this assertion names the roster's rather than taking
  // whichever error reached the DOM first.
  assert.equal(
    byClass(byClass(root, "sessions-view")[0], "error")[0].textContent,
    "session registry unavailable.",
  );
  assert.equal(byClass(root, "session-card").length, 0);
  assert.equal(
    byClass(root, "item-button").find(
      (button) => button.textContent === "Reclaim stale",
    ).disabled,
    true,
  );
  mounted.unmount();
});

test("Sessions styles use theme tokens and collapse stats and cards on narrow screens", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_secondary_views.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-card \{[\s\S]*background: var\(--yoke-surface\);/,
  );
  assert.match(css, /\.session-harness\.h-claude \{[\s\S]*--yoke-h-claude/);
  assert.match(css, /\.session-harness\.h-codex \{[\s\S]*--yoke-h-codex/);
  assert.match(
    css,
    /@media \(max-width: 760px\)[\s\S]*\.sessions-stats \{[\s\S]*repeat\(2,[\s\S]*\.session-grid \{ grid-template-columns: 1fr; \}/,
  );
});

test("The session card identity line wraps instead of truncating its labels", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  // A card whose harness, lane, and operator each render as an initial plus an
  // ellipsis names nothing; the row breaks to a second line instead.
  assert.match(
    css,
    /\.session-top \{[^}]*flex-wrap: wrap;[^}]*gap: 6px 9px;/s,
  );
  assert.match(
    css,
    /\.session-top > \* \{[^}]*max-width: 100%;[^}]*overflow-wrap: anywhere;/,
  );
  for (const rule of ["session-executor", "session-operator"]) {
    const block = css.match(
      new RegExp(`\\n\\.universe-app-root \\.${rule} \\{([^}]*)\\}`),
    )[1];
    assert.doesNotMatch(block, /text-overflow: ellipsis;/);
    assert.doesNotMatch(block, /white-space: nowrap;/);
    assert.doesNotMatch(block, /overflow: hidden;/);
  }
});

test("Sessions sizes its stats and keeps the message row to one text line", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.sessions-stats \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/,
  );
  assert.match(css, /\.sessions-stats \.stat \{[^}]*padding: 9px 13px;/s);
  assert.match(css, /\.sessions-stats \.stat \.n \{ font-size: 17px; font-weight: 700; \}/);
  assert.match(css, /\.sessions-stats \.stat \.l \{[^}]*font-weight: 400; \}/);
  assert.match(css, /\.session-item-title \{[^}]*font-weight: 700;/s);
  assert.match(
    css,
    /\.session-latest-message \{[^}]*flex-wrap: nowrap;[^}]*line-height: 1\.2;[^}]*white-space: nowrap;/,
  );
  assert.match(
    css,
    /\.session-message-button \{[^}]*height: 1\.2em;[^}]*min-height: 0;[^}]*padding: 0 5px;/,
  );
  assert.match(
    css,
    /\.session-message-badge,[\s\S]*\.session-kill-badge \{[\s\S]*padding: 2px 8px;[\s\S]*font-size: 11px;/,
  );
  assert.match(
    css,
    /\.session-card\.is-stale \{ background: var\(--yoke-crit-bg\); \}/,
  );
  assert.doesNotMatch(
    css,
    /\.session-latest-message \.session-message-badge \{[^}]*padding-block: 0;/,
  );
});

test("The roster toolbar uses compact prototype controls without flattening fields", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_control.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /\.universe-app-root \{\s*--session-control-height: 34px;\s*\}/);
  assert.match(
    css,
    /\.session-roster-filter \{[^}]*min-height: var\(--session-control-height\);[^}]*border: 1px solid var\(--yoke-border\);[^}]*border-radius: 9px;/s,
  );
  assert.match(css, /\.session-filter-search \{[^}]*max-width: 340px;[^}]*flex: 1 1 240px;/s);
  assert.match(css, /\.session-filter-actions \{[^}]*margin-left: auto;/s);
  const shared = css.match(
    /\.universe-app-root \.session-control-input \{([^}]*)\}/,
  )[1];
  assert.match(shared, /min-height: var\(--session-control-height\);/);
  assert.match(
    css,
    /\.universe-app-root \.session-message-body \{[^}]*min-height: 130px;[^}]*resize: vertical;/,
  );
});
