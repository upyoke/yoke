import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
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

test("Sessions matches the prototype's runtime, assignment, lane, and operator anatomy", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const originalNow = Date.now;
  Date.now = () => Date.parse("2026-07-26T12:05:00Z");
  t.after(() => { Date.now = originalNow; });
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
        current_item_status: "implementing",
        owns_current_item: true, work_role: "integration",
        claim_started_at: "2026-07-26T12:00:00Z",
        activity_at: "2026-07-26T12:04:00Z",
        claims: [{
          target_kind: "item", target: "YOK-2228",
          item_status: "implementing", item_workflow_id: "blitz",
        }],
        holdings: { current: [{
          holding_kind: "work_claim", target_kind: "item", target: "YOK-2228",
          item_title: "Execute WORKFLOW-TYPES",
        }], previous: [], previous_remainder: 0 },
        claimed_blitz_worktree_ids: [101, 102],
        machine_id: "machine-1", machine_name: "test-mac", relay: "connected",
        messageability: {
          messageable: true, wake_available: true, relay_connected: true,
        },
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
        current_item_status: "implementing",
        owns_current_item: false, work_role: "worker",
        claim_started_at: null,
        activity_at: "2026-07-26T11:40:00Z",
        claims: [],
        holdings: { current: [], previous: [], previous_remainder: 0 },
        claimed_blitz_worktree_ids: [],
        machine_id: "machine-2", relay: "unavailable",
        messageability: {
          messageable: true, wake_available: false, relay_connected: false,
        },
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
        memberDirectory: { 2: "stale-directory-name" },
      },
    },
  });
  await settle();

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
  const state = byClass(root, "session-roster-filter").find(
    (field) => field.children[0].textContent === "State",
  ).children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));
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
      ["1", "item claimed"],
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
  // Parked is the only mode the card badges; resume and wait render nothing.
  assert.deepEqual(
    byClass(root, "session-parked-badge").filter((n) => !n.hidden).map((n) => n.textContent),
    [],
  );
  // The mode pill is gone; the lane names the session beside its harness and
  // the relay pill is the one reachability fact the card keeps.
  assert.deepEqual(
    byClass(root, "session-lane").map((lane) => lane.textContent),
    ["🧭 Integration", "DARIUS"],
  );
  assert.deepEqual(
    byClass(root, "pill").map((pill) => [pill.textContent, pill.className]),
    [
      ["test-mac", "pill good session-relay-pill"],
      ["blitz · implementing", "pill run session-item-stage"],
      ["machine-2", "pill crit session-relay-pill"],
    ],
  );
  assert.deepEqual(
    byClass(root, "session-relay-warning").map((node) => node.textContent),
    ["no relay connected"],
  );
  assert.deepEqual(
    byClass(root, "session-lock").map(
      (marker) => [marker.textContent, marker.className, marker.title],
    ),
    [["🔒", "session-lock", "work claim — this session holds it"]],
  );
  assert.deepEqual(
    byClass(root, "session-attached").map(
      (marker) => [marker.textContent, marker.className],
    ),
    [["↳", "session-attached"]],
  );
  // Holding rows carry no present-day item stage. The attached context row may
  // still name its live item stage, and neither path exposes a raw target kind.
  assert.equal(byClass(root, "session-work-role").length, 0);
  // The removed anatomy. `session-id` and `session-actor-avatar` still exist
  // for the overview table, so their absence here is the card's own change.
  assert.equal(byClass(root, "session-id").length, 0);
  assert.equal(byClass(root, "session-actor-avatar").length, 0);
  assert.deepEqual(
    byClass(root, "session-operator").map((operator) => operator.textContent),
    ["Ben", "preview-ci"],
  );
  for (const gone of [
    "Executor version:", "Messageable:", "Stale cleanup:", "Why active:",
    "Machine:",
  ]) assert.ok(!visibleText(root).includes(gone), gone);
  assert.equal(byClass(root, "session-item-link")[0].href, "#/items/2228?project=1");
  const cardText = cards.map(visibleText);
  for (const expected of [
    "claude-code", "YOK-2228", "Execute WORKFLOW-TYPES",
    "🧭 Integration", "claude-opus-4-8", "claim held", "idle", "Ben",
    "Relay:", "test-mac",
  ]) {
    assert.ok(cardText[0].includes(expected), expected);
  }
  for (const expected of [
    "codex", "DARIUS", "gpt-5.6-sol", "worktree attached",
    "stale", "preview-ci", "no relay connected",
  ]) {
    assert.ok(cardText[1].includes(expected), expected);
  }
  for (const gone of ["a7b4pl", "v8c2qa", "resume", "wait"]) {
    assert.ok(!cardText.join(" ").includes(gone), gone);
  }
  // Messaging offers a button only where it would actually arrive; the stale
  // session with no relay gets the one condition standing in the way.
  assert.deepEqual(
    byClass(cards[0], "item-button").map((button) => button.textContent),
    ["Message"],
  );
  assert.equal(byClass(cards[1], "item-button").length, 0);
  assert.equal(
    byClass(cards[1], "session-messaging-blocked")[0].textContent,
    "Messaging unavailable: no relay is connected on this session's machine.",
  );
  // The server-active card can be quiet without being recategorized as stale.
  assert.deepEqual(
    byClass(cards[0], "session-age-prefix").map((node) => node.textContent),
    ["claim held ", "idle "],
  );
  assert.deepEqual(
    byClass(cards[1], "session-age-prefix").map((node) => node.textContent),
    ["worktree attached ", "stale "],
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

test("Sessions card exposes the parked reason without rendering it inline", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const rows = [
    {
      session_id: "parked-1", liveness: "active",
      execution_lane: "DARIUS", mode: "parked",
      parked_reason: "waiting on YOK-2546",
      executor: "codex", model: "gpt-5.6-sol",
      executor_mark: "X", executor_class_name: "h-codex",
      actor_id: 2, actor_kind: "human", actor_label: "Ben",
      project_id: 1, project: "yoke",
      activity_at: "2026-07-26T11:40:00Z",
      claims: [],
    },
    {
      session_id: "wait-1", liveness: "active",
      execution_lane: "ALTMAN", mode: "wait",
      executor: "claude-code", model: "claude-opus-4-8",
      executor_mark: "A", executor_class_name: "h-claude",
      actor_id: 2, actor_kind: "human", actor_label: "Ben",
      project_id: 1, project: "yoke",
      activity_at: "2026-07-26T12:04:00Z",
      claims: [],
    },
  ];
  const mounted = mountUniverseApp(root, {
    client: sessionsClient(rows, []),
  });
  await settle();
  assert.deepEqual(
    byClass(root, "session-parked-badge").filter((n) => !n.hidden).map(
      (n) => [n.textContent, n.title, n.attributes.get("aria-label")],
    ),
    [["parked", "waiting on YOK-2546", "parked: waiting on YOK-2546"]],
  );
  mounted.unmount();
});
