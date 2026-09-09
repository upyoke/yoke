import assert from "node:assert/strict";
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

function button(root, label) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === label,
  );
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

function shellClient(requests, handlers) {
  return {
    async call(request) {
      requests.push(request);
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

test("message history directs new composition to the roster", async (t) => {
  const requests = [];
  const client = shellClient(requests, {
    "session_control.message.list": () => ok({
      messages: [], count: 0, actionable_count: 0,
      settled_matched_count: 0, next_cursor: null,
    }),
  });
  const { root, mounted } = await mountAt(
    t, "#/messages?project=1", client,
  );
  assert.equal(button(root, "Compose message"), undefined);
  assert.ok(allNodes(root).some(
    (node) => node.textContent.includes("Send from the Sessions roster"),
  ));
  mounted.unmount();
});

test("message receipts expose recipient delivery and wake state", async (t) => {
  const requests = [];
  const recipients = [{
    session_id: "session-1", project_id: 1, state: "pending",
    created_at: "2026-08-23T01:00:00Z", wake_attempt_count: 2,
    last_wake_at: "2026-08-23T01:05:00Z", executor_surface: "codex-cli",
  }, {
    session_id: "session-2", project_id: 1, state: "acknowledged",
    wake_attempt_count: 0, acknowledged_at: "2026-08-23T01:06:00Z",
    executor_surface: "codex-cli",
  }, {
    session_id: "session-3", project_id: 1, state: "acknowledged",
    wake_attempt_count: 1, acknowledged_at: "2026-08-23T01:07:00Z",
    executor_surface: "codex-cli",
  }];
  const client = shellClient(requests, {
    "session_control.message.list": () => ok({
      messages: [{
        message_id: "message-1", body: "Please report delivery status.",
        sender_actor_id: 2, sender_actor_label: "ben", sender_actor_kind: "human",
        sender_session_id: "session-sender",
        sender_surface: "harness_session", sender_surface_label: "harness session",
        created_at: "2026-08-23T01:00:00Z",
        needs_attention: true,
        recipients: structuredClone(recipients),
      }],
      count: 1,
      actionable_count: 1,
      settled_matched_count: 0,
      next_cursor: null,
    }),
    "session_control.message.get": () => ok({
      message: {
        message_id: "message-1", body: "Please report delivery status.",
        sender_actor_id: 2, sender_actor_label: "ben", sender_actor_kind: "human",
        sender_session_id: "session-sender", created_at: "2026-08-23T01:00:00Z",
        recipients: structuredClone(recipients),
      },
    }),
    "session_control.message.cancel": () => ok({ message: {} }),
  });
  const { root, mounted } = await mountAt(
    t, "#/messages?project=1", client,
  );
  assert.equal(byClass(root, "session-message-card")[0].getAttribute(
    "data-message-state",
  ), "pending");
  button(root, "Details").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    byClass(root, "session-message-delivery-marker").map((node) => node.textContent),
    ["Wake ×2", "Direct", "Wake ×1"],
  );
  assert.deepEqual(
    byClass(root, "session-message-party").map((node) => node.textContent),
    [
      "ben via session session-sender",
      "codex-cli",
      "codex-cli",
      "codex-cli",
    ],
  );
  const acknowledged = byClass(root, "session-message-recipient-status")[1];
  assert.equal(acknowledged.children[0].textContent, "Acknowledged ");
  assert.equal(acknowledged.children[1].getAttribute("datetime"), "2026-08-23T01:06:00.000Z");
  button(root, "Cancel").dispatchEvent(new Event("click"));
  await settle();
  assert.ok(requests.some(
    (request) => request.function === "session_control.message.cancel"
      && request.payload.message_id === "message-1",
  ));
  mounted.unmount();
});

test("relay tab renders public machine facts without native controls", async (t) => {
  const requests = [];
  const client = shellClient(requests, {
    "machine.list": () => ok({
      machines: [{
        machine_id: "m1", name: "studio", owner: "Ada", retired_at: null,
      }],
      count: 1,
    }),
    "session_control.relay.list": () => ok({
      relays: [{
        relay_id: "machine:m1", machine_id: "m1", hostname: "studio",
        relay_version: "launch.271", state: "active", liveness: "connected",
        surface_versions: { "claude-cli": "2.1.238" }, project_ids: [1],
        last_seen_at: "2026-08-23T04:30:00Z",
      }],
      count: 1,
    }),
  });
  const { root, mounted } = await mountAt(
    t, "#/machines?project=1", client,
  );
  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(text.includes("studio"));
  assert.ok(text.includes("claude-cli 2.1.238"));
  assert.equal(button(root, "Serve once"), undefined);
  mounted.unmount();
});

test("organization Fleet edits only changed registry-backed settings", async (t) => {
  const requests = [];
  let pollSeconds = 60;
  const client = shellClient(requests, {
    "organizations.settings.catalog": () => ok({
      org_id: 1,
      settings: [{
        path: "fleet.relay_poll_seconds", value: pollSeconds, default: 60,
        defaulted: pollSeconds === 60, value_type: "int", minimum: 5,
        meaning: "relay poll interval",
      }, {
        path: "fleet.surface_fallback", value: false, default: false,
        defaulted: true, value_type: "bool", minimum: null,
        meaning: "permit explicit surface fallback",
      }],
    }),
    "organizations.settings.merge": (request) => {
      pollSeconds = request.payload.assignments["fleet.relay_poll_seconds"];
      return ok({ org_id: 1, changed_paths: ["fleet.relay_poll_seconds"] });
    },
  });
  const { root, mounted } = await mountAt(t, "#/organization", client);
  const controls = byClass(root, "session-control-input");
  controls[0].value = "45";
  button(root, "Save fleet policy").dispatchEvent(new Event("click"));
  await settle();
  const merge = requests.find(
    (request) => request.function === "organizations.settings.merge",
  );
  assert.deepEqual(merge.payload.assignments, {
    "fleet.relay_poll_seconds": 45,
  });
  mounted.unmount();
});

test("roster keeps exact message actions on open sessions only", async (t) => {
  const requests = [];
  const base = {
    execution_lane: "DARIUS", mode: "wait", executor: "codex",
    executor_surface: "codex-desktop", executor_version: "26.814.41407",
    machine_id: "machine-1", machine_name: "studio", relay: "connected",
    model: "gpt-5", actor_id: 2, actor_kind: "human", actor_label: "Ben",
    project_id: 1, project: "yoke", current_item: null, claims: [],
    activity_at: "2026-07-26T12:00:00Z",
  };
  const client = shellClient(requests, {
    "sessions.list": (request) => request.payload.open ? ok({ rows: [{
      ...base, session_id: "messageable", liveness: "active",
      messageability: { messageable: true, wake_available: false },
    }, {
      ...base, session_id: "wakeable", liveness: "stale",
      messageability: { messageable: false, wake_available: true },
    }] }) : ok({
      rows: [{
        session_id: "ended-wakeable", liveness: "ended", project_id: 1,
        project: "yoke", executor: "codex", executor_surface: "codex-desktop",
        machine_id: "machine-1", machine_name: "studio",
        activity_at: "2026-07-26T12:00:00Z", current_item: null,
      }],
      matched_count: 1, next_cursor: null,
      facets: { projects: [], harnesses: [], machines: [] },
    }),
    "session_control.message.preview": () => ok({
      recipients: [{
        ...base, session_id: "messageable", liveness: "active",
        messageability: { messageable: true, wake_available: false },
      }],
      recipient_count: 1,
      confirmation_token: "confirmed-ended",
    }),
  });
  const { root, mounted } = await mountAt(
    t, "#/sessions?project=1", client,
  );
  const filters = byClass(root, "session-roster-filter");
  const state = filters.find((field) => field.children[0].textContent === "State")
    .children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));
  await settle();
  const cardIds = () => byClass(root, "session-card").map(
    (card) => card.getAttribute("data-session-id"),
  );
  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(text.includes("Relay:") && text.includes("studio"));
  assert.ok(text.includes(
    "Messaging unavailable: this executor surface has no supported "
    + "delivery hook.",
  ));
  const endedCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "ended-wakeable",
  );
  assert.equal(button(endedCard, "Message"), undefined);
  const activeCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "messageable",
  );
  button(activeCard, "Message").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "session-message-selector-sessions").length, 0);
  assert.deepEqual(
    requests.find(
      (request) => request.function === "session_control.message.preview",
    ).payload.selector,
    { session_ids: ["messageable"] },
  );
  state.value = "active";
  state.dispatchEvent(new Event("change"));
  assert.deepEqual(cardIds(), ["messageable", "wakeable"]);
  mounted.unmount();
});
