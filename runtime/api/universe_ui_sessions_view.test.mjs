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
  const filterButtons = byClass(emptyRoot, "session-roster-filters")[0].children
    .filter((node) => node.tagName === "BUTTON");
  assert.deepEqual(
    filterButtons.map((button) => button.textContent),
    ["Clear filters", "Message all", "Reclaim stale"],
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

  assert.equal(
    byClass(root, "error")[0].textContent,
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

test("Sessions sizes its stats and keeps the message row to one text line", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.sessions-stats \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/,
  );
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
    /\.session-latest-message \.session-message-badge \{[^}]*padding-block: 0;/,
  );
});
