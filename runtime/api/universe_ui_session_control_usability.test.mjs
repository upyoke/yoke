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
  const { root, mounted } = await mountAt(t, "#/sessions/messages?project=1", {
    "session_control.message.list": () => ok({
      messages: [{
        message_id: "message-opaque-id",
        body: "Please verify the production delivery receipt.",
        sender_session_id: "sender-1",
        created_at: "2026-08-23T01:02:03Z",
        recipients: [{
          session_id: "recipient-1", project_id: 1, state: "injected",
        }],
      }],
      count: 1,
    }),
  });

  assert.equal(
    byClass(root, "session-message-excerpt")[0].textContent,
    "Please verify the production delivery receipt.",
  );
  assert.equal(byClass(root, "session-message-sender")[0].textContent, "From sender-1");
  assert.ok(allNodes(root).some(
    (node) => node._textContent === "2026-08-23 01:02 UTC",
  ));
  assert.equal(byClass(root, "session-control-guide").length, 1);
  assert.equal(allNodes(root).filter((node) => node.tagName === "THEAD").length, 1);
  assert.ok(allNodes(root).filter((node) => node.tagName === "TH").every(
    (node) => node.getAttribute("scope") === "col",
  ));
  mounted.unmount();
});

test("compose explains exact preview and blocks an unroutable recipient", async (t) => {
  const { root, mounted } = await mountAt(t, "#/sessions/messages?project=1", {
    "session_control.message.list": () => ok({ messages: [], count: 0 }),
    "session_control.message.preview": () => ok({
      recipients: [{
        session_id: "session-1", project: "yoke", liveness: "active",
        messageability: { messageable: false }, resolution: ["session_id"],
      }],
      recipient_count: 1,
    }),
  });
  button(root, "Compose message").dispatchEvent(new Event("click"));
  assert.ok(byClass(root, "session-control-help")[0].textContent.includes(
    "preview the exact sessions",
  ));
  assert.equal(
    byClass(root, "session-message-selector-items")[0].placeholder,
    "For example, PROJECT-123",
  );
  byClass(root, "session-message-selector-sessions")[0].value = "session-1";
  byClass(root, "session-message-body")[0].value = "Test delivery.";
  button(root, "Preview recipients").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    byClass(root, "session-control-status").at(-1).textContent,
    "1 exact recipient resolved; 1 session cannot receive Fleet messages. Choose a session marked Messageable in the roster.",
  );
  assert.equal(button(root, "Send message").disabled, true);
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
