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

function lastButton(root, label) {
  return allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === label,
  ).at(-1);
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
    "session_control.message.list": () => ok({ messages: [], count: 0 }),
  });
  const { root, mounted } = await mountAt(
    t, "#/sessions/messages?project=1", client,
  );
  assert.equal(button(root, "Compose message"), undefined);
  assert.ok(allNodes(root).some(
    (node) => node.textContent.includes("filter the roster and choose Message all"),
  ));
  mounted.unmount();
});

test("launch create uses relay-discovered surfaces and an exact preview", async (t) => {
  const requests = [];
  const relay = {
    relay_id: "machine:m1", machine_id: "m1", hostname: "studio",
    state: "active", surface_versions: { "codex-desktop": "26.814.41407" },
    project_ids: [1],
  };
  const client = shellClient(requests, {
    "session_control.launch.list": () => ok({
      launches: [{
        launch_id: "launch-existing", state: "awaiting_registration",
        requested_surface: "codex-desktop", selected_surface: "codex-desktop",
        assigned_machine_id: "m1",
        created_at: "2026-08-23T01:00:00Z",
        assigned_at: "2026-08-23T01:01:00Z",
        launching_at: "2026-08-23T01:02:00Z",
        awaiting_registration_at: "2026-08-23T01:03:00Z",
      }],
      count: 1,
    }),
    "sessions.list": () => ok({ rows: [{ model: "gpt-5.6-sol" }] }),
    "session_control.relay.list": () => ok({ relays: [relay], count: 1 }),
    "session_control.launch.preview": () => ok({
      outcome: "assigned", requested_surface: "codex-desktop", requested_model: "gpt-5.6-sol",
      selected_surface: "codex-desktop", fallback_used: false,
      launchable: true, eligible_relays: [relay], selected_relay: relay,
    }),
    "session_control.launch.create": () => ok({
      launch: { launch_id: "launch-1", state: "assigned" },
      preview: {}, deduplicated: false,
    }),
  });
  const { root, mounted } = await mountAt(
    t, "#/sessions/launches?project=1", client,
  );
  const timelineText = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(timelineText.includes(
    "codex-desktop requested · codex-desktop selected · m1",
  ));
  assert.equal(
    byClass(root, "session-launch-card")[0].getAttribute("data-launch-id"),
    "launch-existing",
  );
  assert.ok(timelineText.includes("launching:"));
  assert.ok(timelineText.includes("awaiting registration:"));
  assert.ok(timelineText.includes("2026-08-23 01:02 UTC"));
  button(root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  const inputs = byClass(root, "session-control-input");
  assert.equal(inputs[0].value, "1");
  assert.equal(inputs[1].value, "codex-desktop");
  inputs[3].value = "gpt-5.6-sol";
  inputs[4].value = "Open the assigned work and report through hooks.";
  button(root, "Preview launch").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(lastButton(root, "Create session").disabled, false);
  lastButton(root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    byClass(root, "session-control-status")[0].textContent,
    "launch-1 created. Tracking registration below.",
  );
  const preview = requests.find(
    (request) => request.function === "session_control.launch.preview",
  );
  const create = requests.find(
    (request) => request.function === "session_control.launch.create",
  );
  assert.equal(preview.payload.executor_surface, "codex-desktop");
  assert.equal(preview.payload.model, "gpt-5.6-sol");
  assert.equal(create.payload.executor_surface, preview.payload.executor_surface);
  assert.equal(create.payload.allow_surface_fallback, false);
  assert.ok(create.payload.idempotency_key.startsWith("workbench-launch:"));
  assert.equal(
    create.payload.instructions,
    "Open the assigned work and report through hooks.",
  );
  mounted.unmount();
});

test("message receipts expose recipient delivery and wake state", async (t) => {
  const requests = [];
  const client = shellClient(requests, {
    "session_control.message.list": () => ok({
      messages: [{
        message_id: "message-1", created_at: "2026-08-23T01:00:00Z",
        recipients: [{
          session_id: "session-1", project_id: 1, state: "pending",
          wake_attempt_count: 2, last_wake_at: "2026-08-23T01:05:00Z",
        }, {
          session_id: "session-2", project_id: 1, state: "acknowledged",
          wake_attempt_count: 0, wake_after: "2026-08-23T01:06:00Z",
        }, {
          session_id: "session-3", project_id: 1, state: "acknowledged",
          wake_attempt_count: 1, last_wake_at: "2026-08-23T01:07:00Z",
        }],
      }],
      count: 1,
    }),
    "session_control.message.cancel": () => ok({ message: {} }),
  });
  const { root, mounted } = await mountAt(
    t, "#/sessions/messages?project=1", client,
  );
  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(text.includes("session-1 · pending · 2 wake attempts"));
  assert.ok(text.includes(
    "session-2 · acknowledged · delivery acknowledged without a wake",
  ));
  assert.ok(text.includes(
    "session-3 · acknowledged · delivery acknowledged after 1 wake attempt",
  ));
  assert.equal(text.includes("wake eligible"), false);
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
    t, "#/sessions/relays?project=1", client,
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

test("roster includes ended sessions with exact message actions", async (t) => {
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
    "sessions.list": () => ok({ rows: [{
      ...base, session_id: "messageable", liveness: "active",
      messageability: { messageable: true, wake_available: false },
    }, {
      ...base, session_id: "wakeable", liveness: "stale",
      messageability: { messageable: false, wake_available: true },
    }, {
      ...base, session_id: "ended-wakeable", liveness: "ended",
      messageability: { messageable: true, wake_available: true },
    }] }),
    "session_control.message.preview": () => ok({
      recipients: [{
        ...base, session_id: "ended-wakeable", liveness: "ended",
        messageability: { messageable: true, wake_available: true },
      }],
      recipient_count: 1,
      confirmation_token: "confirmed-ended",
    }),
  });
  const { root, mounted } = await mountAt(
    t, "#/sessions/roster?project=1", client,
  );
  const filters = byClass(root, "session-roster-filter");
  const state = filters.find((field) => field.children[0].textContent === "State")
    .children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));
  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(text.includes("Executor version: 26.814.41407"));
  assert.ok(text.includes("Machine: studio · relay connected"));
  assert.ok(text.includes(
    "Messageable: durable delivery and automatic restart are available.",
  ));
  const endedCard = byClass(root, "session-card").find(
    (card) => byClass(card, "session-id")[0]?.textContent === "ended-wakeable",
  );
  button(endedCard, "Message").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "session-message-selector-sessions").length, 0);
  assert.deepEqual(
    requests.find(
      (request) => request.function === "session_control.message.preview",
    ).payload.selector,
    { session_ids: ["ended-wakeable"] },
  );
  state.value = "stale";
  state.dispatchEvent(new Event("change"));
  assert.deepEqual(
    byClass(root, "session-id").map((node) => node.textContent),
    ["wakeable"],
  );
  mounted.unmount();
});
