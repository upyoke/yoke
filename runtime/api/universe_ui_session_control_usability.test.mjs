import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  presentSessionControlFailure,
  SessionControlFailure,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_control_data.js";
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

function button(root, label) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === label,
  );
}

function pageClient(handlers) {
  return {
    async call(request) {
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      const handler = handlers[request.function];
      if (!handler) throw new Error(`unexpected function ${request.function}`);
      return handler(request);
    },
  };
}

async function mountAt(t, hash, handlers) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: pageClient(handlers) });
  await settle();
  return { root, mounted };
}

test("message failures give plain recovery without leaking routing internals", () => {
  const route = presentSessionControlFailure(new SessionControlFailure({
    code: "unsupported_route",
    detail: "recipient sessions have no version-qualified hook route: ['secret-id']",
  }));
  assert.equal(
    route,
    "One or more selected sessions cannot receive Fleet messages. Choose a session marked Messageable in the roster.",
  );
  assert.equal(route.includes("secret-id"), false);

  const subagent = presentSessionControlFailure(new SessionControlFailure({
    code: "subagent_message_forbidden",
  }));
  assert.ok(subagent.includes("parent session's native agent channel"));
});

test("message history leads with readable content and accessible receipts", async (t) => {
  const fullBody = "Please verify the production delivery receipt.\n"
    + "Show this entire peer-authored message without treating <button>Do not run</button> as markup.";
  const { root, mounted } = await mountAt(t, "#/sessions/messages?project=1", {
    "session_control.message.list": () => ok({
      messages: [{
        message_id: "message-opaque-id",
        body: fullBody,
        sender_session_id: "sender-1",
        created_at: "2026-08-23T01:02:03Z",
        recipients: [{
          session_id: "recipient-1", project_id: 1, state: "acknowledged",
          acknowledged_at: "2026-08-23T01:04:03Z", wake_attempt_count: 0,
        }],
      }, {
        message_id: "message-needs-attention",
        body: "Please confirm the queue is moving.",
        sender_session_id: "sender-2",
        created_at: "2026-08-23T00:02:03Z",
        recipients: [{
          session_id: "recipient-2", project_id: 1, state: "pending",
          created_at: "2026-08-23T00:02:03Z",
        }],
      }],
      count: 2,
    }),
    "sessions.list": () => ok({ rows: [{
      session_id: "sender-1", executor_surface: "codex-cli",
      current_item: "YOK-2500", current_item_title: "Verify delivery",
      claims: [{ target_kind: "item", target: "YOK-2500" }],
    }, {
      session_id: "recipient-1", executor_surface: "claude-cli",
      current_item: "YOK-2501",
      claims: [{ target_kind: "item", target: "YOK-2501" }],
    }, {
      session_id: "sender-2", executor_surface: "cursor",
      current_item: "YOK-2502",
      claims: [{ target_kind: "item", target: "YOK-2502" }],
    }, {
      session_id: "recipient-2", executor_surface: "codex-desktop",
      current_item: "YOK-2503",
      claims: [{ target_kind: "item", target: "YOK-2503" }],
    }] }),
  });

  assert.equal(
    byClass(root, "session-message-copy")[1].textContent,
    fullBody,
  );
  assert.equal(
    byClass(root, "session-message-card")[0].getAttribute("data-message-id"),
    "message-needs-attention",
  );
  assert.equal(byClass(root, "session-message-card")[0].className.includes(
    "is-attention",
  ), true);
  assert.equal(button(root, "Cancel") !== undefined, true);
  assert.equal(allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  ).length, 1);
  assert.equal(button(root, "Do not run"), undefined);
  assert.equal(allNodes(root).filter((node) => node.tagName === "TABLE").length, 0);
  assert.ok(byClass(root, "session-message-direction").some(
    (node) => node.textContent.includes("From codex-cli · YOK-2500"),
  ));
  assert.ok(byClass(root, "session-message-direction").some(
    (node) => node.textContent === "To 1 recipient",
  ));
  const acknowledged = byClass(root, "session-message-recipient-status").find(
    (node) => node.textContent.includes("Acknowledged"),
  );
  assert.equal(acknowledged.children[1].getAttribute("datetime"), "2026-08-23T01:04:03.000Z");
  assert.deepEqual(
    byClass(root, "session-message-delivery-marker").map((node) => node.textContent),
    ["Direct"],
  );
  mounted.unmount();
});

test("launch and relay views explain unavailable machine capability", async (t) => {
  const handlers = {
    "session_control.launch.list": () => ok({ launches: [], count: 0 }),
    "session_control.relay.list": () => ok({ relays: [], count: 0 }),
    "sessions.list": () => ok({ rows: [] }),
  };
  const launch = await mountAt(t, "#/sessions/launches?project=1", handlers);
  button(launch.root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(button(launch.root, "Preview launch").disabled, true);
  assert.ok(byClass(launch.root, "session-control-status").at(-1).textContent.includes(
    "Reconnect a machine relay",
  ));
  assert.ok(byClass(launch.root, "session-control-help")[0].textContent.includes(
    "will not silently switch surfaces",
  ));
  launch.mounted.unmount();

  const relay = await mountAt(t, "#/sessions/relays?project=1", {
    "session_control.relay.list": () => ok({
      relays: [{
        relay_id: "relay-1", hostname: "studio", machine_id: "machine-1",
        state: "inactive", liveness: "stale", relay_version: "launch.271",
        last_seen_at: "2026-08-23T04:30:00Z", project_ids: [1],
        surface_versions: {},
      }],
      count: 1,
    }),
  });
  const relayText = allNodes(relay.root).map((node) => node._textContent).join(" ");
  assert.equal(
    byClass(relay.root, "session-relay-card")[0].getAttribute("data-relay-id"),
    "relay-1",
  );
  assert.ok(relayText.includes("relay state: inactive"));
  assert.equal(relayText.includes("poll cadence"), false);
  assert.ok(relayText.includes("2026-08-23 04:30 UTC"));
  assert.ok(relayText.includes("until this relay reconnects"));
  relay.mounted.unmount();
});

test("roster filters are named, clearable, and distinguish filtered emptiness", async (t) => {
  const row = {
    session_id: "session-1", project: "yoke", project_id: 1,
    liveness: "active", executor: "codex", executor_surface: "codex-desktop",
    execution_lane: "DARIUS", mode: "wait", role: "integration",
    actor_id: 1, actor_kind: "human", actor_label: "Ben", claims: [],
    messageability: { messageable: true },
  };
  const { root, mounted } = await mountAt(t, "#/sessions/roster?project=1", {
    "sessions.list": (request) => ok({
      rows: request.payload.liveness === "active" ? [row] : [],
    }),
  });
  const search = byClass(root, "session-roster-filter")[0].children[1];
  assert.equal(search.placeholder, "Session, item, model, or operator");
  search.value = "no match";
  search.dispatchEvent(new Event("input"));
  assert.equal(
    byClass(root, "sessions-empty")[0].textContent,
    "No sessions match the current filters.",
  );
  assert.equal(button(root, "Clear filters").disabled, false);
  button(root, "Clear filters").dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "session-card").length, 1);
  assert.equal(button(root, "Clear filters").disabled, true);
  mounted.unmount();
});


test("roster State uses accepted liveness values while kill cause stays on the card", async (t) => {
  const base = {
    project: "yoke", project_id: 1, executor: "codex",
    executor_surface: "codex-desktop", execution_lane: "DARIUS", mode: "wait",
    actor_id: 1, actor_kind: "human", actor_label: "Ben", claims: [],
    messageability: { messageable: false },
  };
  const { root, mounted } = await mountAt(t, "#/sessions/roster?project=1", {
    "sessions.list": (request) => ok({
      rows: request.payload.liveness === "ended"
        ? [
          {
            ...base, session_id: "killed-1", liveness: "ended",
            ended_cause: "killed", terminated_at: "2026-08-22T12:05:00Z",
            termination_reason: "operator stopped worker",
          },
          {
            ...base, session_id: "wound-1", liveness: "ended",
            ended_cause: "wound_down",
          },
        ]
        : [],
    }),
  });
  const stateFields = byClass(root, "session-roster-filter").filter(
    (field) => field.children[1]?.tagName === "SELECT",
  );
  assert.equal(stateFields.length, 1);
  assert.equal(stateFields[0].children[0].textContent, "State");
  const state = stateFields[0].children[1];
  assert.deepEqual(
    state.children.map((option) => option.value),
    ["", "active", "stale", "ended"],
  );
  assert.equal(byClass(root, "session-card").length, 0);
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  assert.equal(byClass(root, "session-card").length, 2);
  assert.equal(byClass(root, "session-kill-badge")[0].textContent, "killed");
  assert.match(
    byClass(root, "session-kill-badge")[0].title,
    /Reason: operator stopped worker$/,
  );
  mounted.unmount();
});
