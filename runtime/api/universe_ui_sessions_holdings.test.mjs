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
          rows: [{ id: 1, slug: "yoke", name: "Yoke", emoji: "🛠" }],
        });
      }
      if (request.function === "sessions.list") {
        return ok({ rows });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

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
        claims: [
          {
            target_kind: "item",
            target: "YOK-2100",
            item_ref: "YOK-2100",
            item_project_id: 1,
            item_project_sequence: 2100,
          },
          { target_kind: "item", target: "YOK-2228" },
          { target_kind: "process", target: "feed" },
        ],
        coordination_leases: [
          { lease_key: "QA_HOST:yoke", owner_kind: "session", project_id: 1 },
          {
            lease_key: "LIVE_DB_MIGRATION:primary",
            owner_kind: "item",
            owner_item_ref: "YOK-2100",
            project_id: 1,
          },
        ],
      },
    ]),
    capabilities: { data: { portability: { mode: "hosted" } } },
  });
  await settle();

  const text = visibleText(root);
  for (const expected of [
    "cursor-desktop", "YOK-2228", "YOK-2100", "feed", "QA_HOST:yoke",
    "LIVE_DB_MIGRATION:primary (YOK-2100)",
    "Execute WORKFLOW-TYPES",
  ]) {
    assert.ok(text.includes(expected), expected);
  }
  assert.deepEqual(
    byClass(root, "session-lease-key").map((node) => node.textContent),
    ["QA_HOST:yoke", "LIVE_DB_MIGRATION:primary (YOK-2100)"],
  );
  assert.deepEqual(
    byClass(root, "session-item-link").map((node) => node.textContent),
    ["YOK-2100", "YOK-2228"],
  );
  assert.equal(byClass(root, "session-hold-target")[0].textContent, "feed");
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
      ["1", "sessions shown"],
      ["2", "items claimed"],
      ["1", "Blitz worktree lanes"],
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
