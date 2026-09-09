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
  const { root, mounted } = await mountAt(t, "#/messages?project=1", {
    "session_control.message.list": () => ok({
      messages: [{
        message_id: "message-opaque-id",
        body: fullBody,
        sender_actor_id: 2,
        sender_actor_label: "ben",
        sender_actor_kind: "human",
        sender_session_id: "sender-1",
        sender_surface: "harness_session",
        sender_surface_label: "harness session",
        created_at: "2026-08-23T01:02:03Z",
        needs_attention: false,
        recipients: [{
          session_id: "recipient-1", project_id: 1, state: "acknowledged",
          acknowledged_at: "2026-08-23T01:04:03Z", wake_attempt_count: 0,
        }],
      }, {
        message_id: "message-needs-attention",
        body: "Please confirm the queue is moving.",
        sender_actor_id: 2,
        sender_actor_label: "ben",
        sender_actor_kind: "human",
        sender_session_id: "sender-2",
        sender_surface: "harness_session",
        sender_surface_label: "harness session",
        created_at: "2026-08-23T00:02:03Z",
        needs_attention: true,
        recipients: [{
          session_id: "recipient-2", project_id: 1, state: "pending",
          created_at: "2026-08-23T00:02:03Z",
        }],
      }],
      count: 2,
      actionable_count: 1,
      settled_matched_count: 1,
      next_cursor: null,
    }),
    "session_control.message.get": (request) => ok({
      message: request.payload.message_id === "message-opaque-id"
        ? {
          message_id: "message-opaque-id", body: fullBody,
          sender_actor_id: 2, sender_actor_label: "ben",
          sender_actor_kind: "human", sender_session_id: "sender-1",
          created_at: "2026-08-23T01:02:03Z",
          recipients: [{
            session_id: "recipient-1", project_id: 1, state: "acknowledged",
            acknowledged_at: "2026-08-23T01:04:03Z", wake_attempt_count: 0,
            executor_surface: "claude-cli",
          }],
        }
        : {},
    }),
  });

  const settledCard = byClass(root, "session-message-card").find(
    (card) => card.getAttribute("data-message-id") === "message-opaque-id",
  );
  const attentionCard = byClass(root, "session-message-card").find(
    (card) => card.getAttribute("data-message-id") === "message-needs-attention",
  );
  assert.equal(
    byClass(settledCard, "session-message-copy")[0].textContent,
    fullBody,
  );
  assert.equal(
    settledCard.getAttribute("data-message-id"),
    "message-opaque-id",
  );
  assert.equal(attentionCard.className.includes("is-attention"), true);
  assert.equal(button(root, "Cancel") !== undefined, true);
  assert.equal(allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  ).length, 1);
  assert.equal(button(root, "Do not run"), undefined);
  assert.equal(allNodes(root).filter((node) => node.tagName === "TABLE").length, 0);
  assert.ok(byClass(root, "session-message-direction").some(
    (node) => node.textContent.includes("From ben via session sender-1"),
  ));
  assert.ok(byClass(root, "session-message-direction").some(
    (node) => node.textContent === "To 1 recipient",
  ));
  allNodes(settledCard).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Details",
  ).dispatchEvent(new Event("click"));
  await settle();
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

test("the machine roster reads a registered machine through its relay", async (t) => {
  const relay = await mountAt(t, "#/machines?project=1", {
    "machine.list": () => ok({
      machines: [{
        machine_id: "machine-1", name: "studio", owner: "Ada", retired_at: null,
      }],
      count: 1,
    }),
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
    byClass(relay.root, "machine-card")[0].getAttribute("data-machine-id"),
    "machine-1",
  );
  assert.ok(relayText.includes("studio"));
  assert.ok(relayText.includes("silent"));
  assert.equal(relayText.includes("poll cadence"), false);
  assert.ok(relayText.includes("not installed on this machine"));
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
  const { root, mounted } = await mountAt(t, "#/sessions?project=1", {
    "sessions.list": (request) => ok({
      rows: request.payload.open ? [row] : [],
    }),
  });
  const search = byClass(root, "session-roster-filter")[0].children[1];
  assert.equal(search.placeholder, "Search sessions, items, models, operators");
  search.value = "no match";
  search.dispatchEvent(new Event("input"));
  assert.equal(
    byClass(root, "sessions-empty")[0].textContent,
    "No sessions match the current filters.",
  );
  assert.equal(button(root, "Clear").disabled, false);
  button(root, "Clear").dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "session-card").length, 1);
  assert.equal(button(root, "Clear").disabled, true);
  mounted.unmount();
});


test("roster State uses accepted liveness values while kill cause stays on the card", async (t) => {
  const base = {
    project: "yoke", project_id: 1, executor: "codex",
    executor_surface: "codex-desktop", execution_lane: "DARIUS", mode: "wait",
    actor_id: 1, actor_kind: "human", actor_label: "Ben", claims: [],
    messageability: { messageable: false },
  };
  const { root, mounted } = await mountAt(t, "#/sessions?project=1", {
    "sessions.list": (request) => request.payload.open ? ok({ rows: [] }) : ok({
      rows: request.payload.history ? [
          {
            ...base, session_id: "killed-1", liveness: "ended",
            activity_at: "2026-08-22T12:05:00Z",
            ended_cause: "killed", terminated_at: "2026-08-22T12:05:00Z",
            termination_reason: "operator stopped worker",
          },
          {
            ...base, session_id: "wound-1", liveness: "ended",
            ended_cause: "wound_down",
          },
        ] : [],
      matched_count: 2, next_cursor: null,
      facets: { projects: [], harnesses: [], machines: [] },
    }),
  });
  const stateField = byClass(root, "session-roster-filter").find(
    (field) => field.children[0]?.textContent === "State",
  );
  const state = stateField.children[1];
  assert.deepEqual(
    state.children.map((option) => option.value),
    ["active", "ended", ""],
  );
  assert.equal(byClass(root, "session-card").length, 0);
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  assert.equal(byClass(root, "session-card").length, 2);
  // The kill rides the card's one timing region, the same region a live card
  // uses for its age, rather than a fact line only ended cards have.
  const killed = byClass(root, "session-card")[0];
  assert.match(byClass(killed, "session-age")[0].textContent, /^killed /);
  assert.equal(byClass(killed, "session-history-reason")[0].textContent,
    "Reason: operator stopped worker");
  // An end nobody recorded a time for says so instead of reading as recent.
  const wound = byClass(root, "session-card")[1];
  assert.match(
    byClass(wound, "session-age")[0].textContent, /^ended · time unavailable/,
  );
  mounted.unmount();
});
