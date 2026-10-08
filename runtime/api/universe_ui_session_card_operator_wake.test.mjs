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
  sessionsClient,
} from "./universe_ui_sessions_view_test_support.mjs";

test("Message button explains a quiet desktop chat waits on its operator", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/sessions?project=1";
  const root = documentNode.createElement("div");
  // The operator owns the wake; hooks deliver the queued message next turn.
  const rows = [
    {
      session_id: "desk-1", liveness: "stale",
      execution_level: "ALTMAN", mode: "wait",
      executor: "claude-code", model: "claude-opus-4-8",
      executor_mark: "A", executor_class_name: "h-claude",
      actor_id: 2, actor_kind: "human", actor_label: "Ben",
      project_id: 1, project: "yoke",
      activity_at: "2026-07-26T11:40:00Z",
      claims: [],
      messageability: {
        messageable: true, wake_available: false, relay_connected: true,
        wake_authority: "operator",
      },
    },
  ];
  const mounted = mountUniverseApp(root, {
    client: sessionsClient(rows, []),
  });
  await settle();
  const state = byClass(root, "session-roster-filter").find(
    (field) => field.children[0].textContent === "State",
  ).children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));
  assert.equal(byClass(root, "session-message-delivery-note").length, 1);
  const buttons = byClass(byClass(root, "session-card")[0], "item-button");
  assert.deepEqual(buttons.map((button) => button.textContent), ["Message"]);
  assert.equal(
    buttons[0].getAttribute("data-tooltip"),
    "Queued — delivered when you wake this session.",
  );
  assert.equal(
    byClass(root, "session-message-delivery-note")[0].textContent,
    "Queued — delivered when you wake this session.",
  );
  mounted.unmount();
});
