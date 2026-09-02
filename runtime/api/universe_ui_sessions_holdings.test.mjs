import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
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

function sessionsClient(rows) {
  return {
    async call(request) {
      if (request.function === "organizations.get") {
        return ok({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return ok({
          rows: [
            { id: 1, slug: "yoke", name: "Yoke", emoji: "🛠" },
            { id: 3, slug: "platform", name: "Platform", emoji: "☁" },
          ],
        });
      }
      if (request.function === "sessions.list") {
        return ok({ rows });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

test("Sessions contains a long relay name and unequal multi-claim cards", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const longMachineName = "beebauman-macbook-pro-16.fios-router.home";
  const mounted = mountUniverseApp(root, {
    client: sessionsClient([
      {
        session_id: "steering-1", liveness: "active",
        execution_lane: "DARIUS", mode: "steer", executor: "codex",
        model: "gpt-5.6-sol", actor_id: 2, actor_kind: "human",
        actor_label: "Ben", project_id: 1, project: "yoke",
        current_item: "YOK-2552", current_item_project_id: 1,
        current_item_project_sequence: 2552,
        current_item_title: "Sessions roster rendering polish",
        current_item_status: "implementing",
        activity_at: "2026-07-26T12:04:00Z",
        claims: [],
        holdings: { current: [
          {
            holding_kind: "work_claim",
            target_kind: "steering", target: "steering for project 1",
            project_id: 1, scope: { project_id: 1 }, strategy_docs: ["CURRENT-PLAN"],
          },
          {
            holding_kind: "strategy_document", target_kind: "strategy_document",
            target: "yoke · CURRENT-PLAN", project_id: 1,
            strategy_doc: "CURRENT-PLAN",
          },
          {
            holding_kind: "work_claim",
            target_kind: "steering", target: "steering for project 3",
            project_id: 3, scope: { project_id: 3 }, strategy_docs: ["CURRENT-PLAN"],
          },
          {
            holding_kind: "strategy_document", target_kind: "strategy_document",
            target: "platform · CURRENT-PLAN", project_id: 3,
            strategy_doc: "CURRENT-PLAN",
          },
          { holding_kind: "work_claim", target_kind: "item", target: "YOK-2552" },
        ], previous: [], previous_remainder: 0 },
        machine_id: "machine-1",
        machine_name: longMachineName, relay: "connected",
        messageability: {
          messageable: true, wake_available: true, relay_connected: true,
        },
      },
      {
        session_id: "single-1", liveness: "active",
        execution_lane: "ALTMAN", mode: "feed", executor: "claude-code",
        model: "claude-opus-4-8", actor_id: 2, actor_kind: "human",
        actor_label: "Ben", project_id: 1, project: "yoke",
        current_item: null, activity_at: "2026-07-26T12:04:00Z",
        claims: [],
        holdings: { current: [
          { holding_kind: "work_claim", target_kind: "process", target: "process feed" },
        ], previous: [], previous_remainder: 0 },
        machine_id: "machine-2",
        machine_name: "test-mac", relay: "connected",
        messageability: {
          messageable: true, wake_available: true, relay_connected: true,
        },
      },
    ]),
    capabilities: { data: { portability: { mode: "hosted" } } },
  });
  await settle();

  const cards = byClass(root, "session-card");
  assert.equal(cards.length, 2);
  // The steering seat's four steering holdings lead the card as its scope,
  // leaving the item claim as the one ordinary holding below them.
  assert.equal(byClass(cards[0], "session-work").length, 1);
  assert.equal(byClass(cards[1], "session-work").length, 1);
  assert.deepEqual(
    byClass(cards[0], "session-steering-scope").map((node) => node.textContent),
    ["yokeCURRENT-PLAN", "platformCURRENT-PLAN"],
  );
  assert.equal(
    byClass(cards[0], "session-steering-lead-label")[0].textContent, "Steering",
  );
  const relay = byClass(cards[0], "session-relay-pill")[0];
  assert.equal(relay.textContent, longMachineName);
  assert.equal(relay.title, longMachineName);
  mounted.unmount();
});

test("Sessions lists every work claim and coordination lease a session holds", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: sessionsClient([
      {
        session_id: "multi-1", liveness: "active",
        execution_lane: "ALTMAN", lane_label: "Integration", lane_glyph: "🧭",
        mode: "dash", executor: "claude-code",
        executor_surface: "cursor-desktop",
        model: "claude-opus-4-8",
        executor_mark: "A", executor_class_name: "h-claude",
        actor_id: 2, actor_kind: "human", actor_label: "Ben",
        project_id: 1, project: "yoke",
        current_item: "YOK-2228",
        current_item_project_id: 1,
        current_item_project_sequence: 2228,
        current_item_title: "Execute WORKFLOW-TYPES",
        current_item_workflow_id: "blitz",
        owns_current_item: true, work_role: "integration",
        claim_started_at: "2026-07-26T12:00:00Z",
        activity_at: "2026-07-26T12:04:00Z",
        claims: [],
        holdings: { current: [
          {
            holding_kind: "work_claim",
            target_kind: "item",
            target: "YOK-2100",
            item_ref: "YOK-2100",
            item_project_id: 1,
            item_project_sequence: 2100,
          },
          {
            holding_kind: "work_claim", target_kind: "item", target: "YOK-2228",
            item_title: "Execute WORKFLOW-TYPES",
          },
          {
            holding_kind: "work_claim", target_kind: "process", target: "process feed",
          },
          {
            holding_kind: "coordination", target_kind: "qa_admission",
            target: "QA_HOST:test-mac",
          },
          {
            holding_kind: "coordination", target_kind: "migration_serialization",
            target: "LIVE_DB_MIGRATION:primary",
            owner_item_ref: "YOK-2100",
          },
        ], previous: [], previous_remainder: 0 },
      },
    ]),
    capabilities: { data: { portability: { mode: "hosted" } } },
  });
  await settle();

  const text = visibleText(root);
  for (const expected of [
    "cursor-desktop", "YOK-2228", "YOK-2100", "process feed",
    "QA_HOST:test-mac", "LIVE_DB_MIGRATION:primary (YOK-2100)",
    "Execute WORKFLOW-TYPES",
  ]) {
    assert.ok(text.includes(expected), expected);
  }
  assert.deepEqual(
    byClass(root, "session-lease-key").map((node) => node.textContent),
    ["QA_HOST:test-mac", "LIVE_DB_MIGRATION:primary (YOK-2100)"],
  );
  assert.equal(byClass(root, "session-work").length, 5);
  assert.ok(!text.includes("qa_admission"), "no raw target_kind label");
  assert.deepEqual(
    byClass(root, "session-item-link").map((node) => node.textContent),
    ["YOK-2100", "YOK-2228"],
  );
  assert.equal(
    byClass(root, "session-hold-target")[0].textContent, "process feed",
  );
  assert.equal(byClass(root, "session-item-stage").length, 0);
  assert.equal(byClass(root, "session-work-role").length, 0);
  assert.equal(
    byClass(root, "session-item-link")[0].href,
    "#/items/2100?project=1",
  );
  assert.equal(
    byClass(root, "session-item-link")[1].href,
    "#/items/2228?project=1",
  );
  assert.deepEqual(
    byClass(root, "sessions-stats")[0].children.map(
      (tile) => [tile.children[0].textContent, tile.children[1].textContent],
    ),
    [
      ["1", "session shown"],
      ["2", "items claimed"],
      ["1", "actor"],
    ],
  );
  mounted.unmount();
});

test("Sessions separates a filed item's attribution from the claim it holds", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const originalNow = Date.now;
  Date.now = () => Date.parse("2026-07-26T12:05:00Z");
  t.after(() => { Date.now = originalNow; });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: sessionsClient([
      {
        session_id: "filer-1", liveness: "active",
        execution_lane: "DARIUS", mode: "wait", executor: "claude-code",
        executor_surface: "claude-desktop", model: "claude-opus-4-8",
        executor_mark: "A", executor_class_name: "h-claude",
        actor_id: 2, actor_kind: "human", actor_label: "Ben",
        project_id: 1, project: "yoke",
        // Focus names an item this session filed; its only claim is
        // elsewhere, so the roster owes an attribution row, not a lock.
        current_item: "YOK-4102",
        current_item_project_id: 1,
        current_item_project_sequence: 4102,
        current_item_title: "Filed while claimed",
        current_item_status: "refining-idea",
        owns_current_item: false, work_role: null,
        claim_started_at: null,
        activity_at: "2026-07-26T12:04:00Z",
        claims: [],
        holdings: { current: [{
          holding_kind: "work_claim", target_kind: "item", target: "YOK-4090",
        }], previous: [], previous_remainder: 0 },
      },
    ]),
    capabilities: { data: { portability: { mode: "hosted" } } },
  });
  await settle();

  assert.deepEqual(
    byClass(root, "session-lock").map((node) => node.textContent),
    ["💼"],
  );
  const attributed = byClass(root, "session-attached");
  assert.deepEqual(attributed.map((node) => node.textContent), ["↳"]);
  assert.match(attributed[0].title, /^filed or updated by this session/);
  assert.equal(byClass(root, "session-work-role").length, 0);
  assert.deepEqual(
    byClass(root, "session-item-stage").map((node) => node.textContent),
    ["refining-idea"],
  );
  const text = visibleText(root);
  assert.ok(!text.includes("worktree attached"), "no worktree line");
  const prefixes = byClass(root, "session-age-prefix").map((n) => n.textContent);
  assert.deepEqual(
    prefixes, ["claim held ", "idle "],
    "currently held claim leads the meta line; filed stays a body row",
  );
  assert.deepEqual(
    byClass(root, "sessions-stats")[0].children.map(
      (tile) => [tile.children[0].textContent, tile.children[1].textContent],
    ),
    [
      ["1", "session shown"],
      ["1", "item claimed"],
      ["1", "actor"],
    ],
  );
  mounted.unmount();
});

test("Sessions lease keys share the mono typeface of item refs", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /\.session-lease-key,/);
});

function sessionCss(name) {
  return readFileSync(new URL(
    `../../packages/yoke-core/src/yoke_core/ui/static/${name}`,
    import.meta.url,
  ), "utf8");
}

test("Session cards contain variable text and stretch to their grid row", () => {
  const css = sessionCss("universe_sessions.css");
  // A row of peers reads as a row only when the cards end on one line, which
  // is the grid's own default: the card must not opt back out of it.
  assert.match(
    sessionCss("universe_secondary_activity.css"),
    /\.session-grid \{[^}]*display: grid;/,
  );
  assert.ok(
    !/\.session-card \{[^}]*align-self/.test(css),
    "cards must inherit the grid's per-row stretch, not align to start",
  );
  assert.match(css, /\.session-work > \* \{[^}]*overflow-wrap: anywhere;/);
  assert.match(css, /\.session-relay-machine \{[^}]*text-overflow: ellipsis;/);
});

test("The relay pill is sized by its machine name and capped, never grown", () => {
  const css = sessionCss("universe_sessions.css");
  const pill = css.match(/\.session-relay-pill \{([^}]*)\}/)[1];
  // Growing is what made a four-character name render as a full-width bar; the
  // cap is what keeps the long name truncating instead of overflowing.
  assert.ok(!/flex/.test(pill), "the pill must not claim spare row width");
  assert.match(pill, /max-width: \d+ch;/);
  assert.match(pill, /min-width: 0;/);
});
