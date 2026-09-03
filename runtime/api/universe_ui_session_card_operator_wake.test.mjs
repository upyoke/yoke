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
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  // Yoke never resumes this window, so delivery stays available and the
  // Message button remains, because the hook still carries the message on
  // the operator's next turn. The card already shows the wait in its parked
  // badge and footer, so that mechanic rides the button's tooltip instead of
  // a standalone line.
  const rows = [
    {
      session_id: "desk-1", liveness: "stale",
      execution_lane: "ALTMAN", mode: "wait",
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
  assert.equal(byClass(root, "session-messaging-blocked").length, 0);
  const buttons = byClass(byClass(root, "session-card")[0], "item-button");
  assert.deepEqual(buttons.map((button) => button.textContent), ["Message"]);
  assert.equal(
    buttons[0].title,
    "Waiting for the operator to wake it: a message is delivered when they "
      + "next type anything in this chat.",
  );
  mounted.unmount();
});
