import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function visibleText(root) {
  return allNodes(root).map((node) => node.textContent || "").join(" ");
}

function sessionsClient(rows, requests, mutation = null) {
  return {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return ok({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return ok({
          rows: [{ id: 1, slug: "yoke", name: "Yoke", emoji: "🛠" }],
        });
      }
      if (request.function === "sessions.list") {
        return ok({ rows: typeof rows === "function" ? rows() : rows });
      }
      if (request.function === "sessions.reclaim_stale" && mutation) {
        return mutation(request);
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

test("Sessions matches the prototype's runtime, assignment, lane, and operator anatomy", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  let reclaimed = false;
  const rows = () => {
    const result = [
      {
        session_id: "a7b4pl", liveness: "active",
        execution_lane: "ALTMAN", lane_label: "Integration", lane_glyph: "🧭",
        mode: "resume", executor: "claude-code", model: "claude-opus-4-8",
        executor_mark: "A", executor_class_name: "h-claude",
        actor_id: 2, actor_kind: "human", actor_label: "Ben",
        project_id: 7, project: "platform",
        current_item: "YOK-2228",
        current_item_project_id: 1,
        current_item_project_sequence: 2228,
        current_item_title: "Execute WORKFLOW-TYPES",
        current_item_workflow_id: "blitz",
        current_item_workflow_version_id: 1,
        owns_current_item: true, work_role: "integration",
        claim_started_at: "2026-07-26T12:00:00Z",
        activity_at: "2026-07-26T12:04:00Z",
        claims: [{ target_kind: "item", target: "YOK-2228" }],
        claimed_blitz_worktree_ids: [101, 102],
      },
      {
        session_id: "v8c2qa", liveness: "stale",
        execution_lane: "DARIUS", mode: "wait",
        executor: "codex", model: "gpt-5.6-sol",
        executor_mark: "X", executor_class_name: "h-codex",
        actor_id: 7, actor_kind: "system", actor_label: "preview-ci",
        project_id: 7, project: "platform",
        current_item: "YOK-2228",
        current_item_project_id: 1,
        current_item_project_sequence: 2228,
        current_item_title: "Execute WORKFLOW-TYPES",
        current_item_workflow_id: "blitz",
        current_item_workflow_version_id: 1,
        owns_current_item: false, work_role: "worker",
        claim_started_at: null,
        activity_at: "2026-07-26T11:40:00Z",
        claims: [],
        claimed_blitz_worktree_ids: [],
      },
    ];
    return reclaimed ? result.slice(0, 1) : result;
  };
  const client = sessionsClient(rows, requests, (request) => {
    assert.deepEqual(request, {
      function: "sessions.reclaim_stale",
      payload: { confirm: true, project_ids: [1] },
    });
    reclaimed = true;
    return ok({ total_reclaimed: 1 });
  });

  const mounted = mountUniverseApp(root, {
    client,
    capabilities: {
      data: {
        portability: { mode: "hosted" },
        memberDirectory: { 2: "ben" },
      },
    },
  });
  await settle();
  const state = byClass(root, "session-roster-filter").find(
    (field) => field.children[0].textContent === "State",
  ).children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));

  assert.deepEqual(
    requests.filter((request) => request.function === "sessions.list"),
    [
      {
        function: "sessions.list",
        payload: { project: "1", liveness: "active", limit: 500 },
      },
      {
        function: "sessions.list",
        payload: { project: "1", liveness: "stale", limit: 500 },
      },
      {
        function: "sessions.list",
        payload: { project: "1", liveness: "ended", limit: 500 },
      },
    ],
  );
  assert.equal(byClass(root, "title")[0].textContent, "Sessions");
  assert.equal(
    byClass(root, "subtitle")[0].textContent,
    "Every harness session running against this universe, and what each one holds.",
  );
  assert.deepEqual(
    byClass(root, "sessions-stats")[0].children.map(
      (tile) => [tile.children[0].textContent, tile.children[1].textContent],
    ),
    [
      ["2", "sessions shown"],
      ["1", "items claimed"],
      ["2", "actors"],
    ],
  );

  const cards = byClass(root, "session-card");
  assert.equal(cards.length, 2);
  assert.deepEqual(
    cards.map((card) => card.attributes.get("data-liveness")),
    ["active", "stale"],
  );
  assert.deepEqual(
    cards.map((card) => card.attributes.get("data-session-id")),
    ["a7b4pl", "v8c2qa"],
  );
  assert.deepEqual(
    byClass(root, "session-harness").map(
      (badge) => [badge.textContent, badge.className],
    ),
    [
      ["A", "session-harness h-claude"],
      ["X", "session-harness h-codex"],
    ],
  );
  assert.deepEqual(
    byClass(root, "pill").map((pill) => [pill.textContent, pill.className]),
    [["resume", "pill run"], ["wait", "pill idle"]],
  );
  assert.deepEqual(
    byClass(root, "session-lock").map(
      (marker) => [marker.textContent, marker.className],
    ),
    [["🔒", "session-lock"]],
  );
  assert.deepEqual(
    byClass(root, "session-attached").map(
      (marker) => [marker.textContent, marker.className],
    ),
    [["↳", "session-attached"]],
  );
  assert.deepEqual(
    byClass(root, "session-work-role").map((node) => node.textContent),
    ["integration", "worker"],
  );
  assert.equal(byClass(root, "session-item-link")[0].href, "#/items/2228?project=1");
  const cardText = cards.map(visibleText);
  for (const expected of [
    "claude-code", "YOK-2228", "Execute WORKFLOW-TYPES",
    "🧭 Integration", "claude-opus-4-8", "claim held", "idle", "ben", "a7b4pl",
  ]) {
    assert.ok(cardText[0].includes(expected), expected);
  }
  for (const expected of [
    "codex", "DARIUS", "gpt-5.6-sol", "worktree attached",
    "idle", "—", "machine", "v8c2qa",
  ]) {
    assert.ok(cardText[1].includes(expected), expected);
  }
  assert.deepEqual(
    byClass(cards[0], "session-age-prefix").map((node) => node.textContent),
    ["claim held ", "idle "],
  );

  const reclaim = byClass(root, "item-button").find(
    (button) => button.textContent === "Reclaim stale",
  );
  assert.equal(reclaim.disabled, false);
  reclaim.dispatchEvent(new Event("click"));
  await settle();
  // Three liveness states, fanned out once on load and once after reclaim.
  assert.equal(
    requests.filter((request) => request.function === "sessions.list").length,
    6,
  );
  assert.equal(byClass(root, "session-card").length, 1);
  assert.deepEqual(
    byClass(root, "sessions-stats")[0].children.map(
      (tile) => tile.children[0].textContent,
    ),
    ["1", "1", "1"],
  );
  assert.equal(reclaim.disabled, true);
  assert.equal(
    byClass(root, "sessions-action-status")[0].textContent,
    "1 stale session reclaimed",
  );
  mounted.unmount();
});

test("Sessions keeps local identity honest and renders the exact empty state", async (t) => {
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

  assert.equal(byClass(root, "session-operator")[0].textContent, "this machine");
  assert.equal(byClass(root, "session-actor-avatar").length, 0);
  assert.ok(visibleText(root).includes("No actionable work right now"));
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
  assert.equal(
    byClass(emptyRoot, "item-button").find(
      (button) => button.textContent === "Reclaim stale",
    ).disabled,
    true,
  );
  emptyMount.unmount();
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
