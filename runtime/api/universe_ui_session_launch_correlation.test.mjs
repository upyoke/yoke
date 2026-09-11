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


function shellResult(request) {
  if (request.function === "organizations.get") return ok({ name: "Yoke" });
  if (request.function === "projects.list") {
    return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
  }
  return null;
}


test("launch cards show identity correlation and exact registered-session links", async (t) => {
  const launches = [
    {
      launch_id: "launch-matched", project_id: 1, state: "completed",
      created_at: "2026-08-23T05:00:00Z",
      native_session_id: "session-matched", registered_session_id: "session-matched",
      identity_correlation: "matched", instruction_delivery: "delivered",
      result_code: "native_created",
      requested_model: "gpt-5.6-sol",
      requested_reasoning_effort: "xhigh",
      requested_context_window_tokens: 1_000_000,
      resolved_model: "gpt-5.6-sol",
      resolved_reasoning_effort: "xhigh",
      resolved_context_window_tokens: 1_000_000,
      result_evidence: {
        adapter_revision: "adapter-v2",
        native_instruction_sha256: "sha256:safe-digest",
        result_code: "native_created",
        surface: "codex-desktop",
        duration_ms: 9,
        exit_code: 0,
        probe_detail: "model does not support effort max",
        token: "secret-token",
        body: "secret-body",
        argv: ["secret-argument"],
        stdout: "secret-stdout",
        stderr: "secret-stderr",
      },
      attestation_hash: "secret-attestation",
    },
    {
      launch_id: "launch-mismatch", project_id: 1, state: "completed",
      created_at: "2026-08-23T04:00:00Z",
      native_session_id: "native-a", registered_session_id: "registered-b",
      identity_correlation: "mismatch", instruction_delivery: "pending",
    },
    {
      launch_id: "launch-awaiting", project_id: 1, state: "awaiting_registration",
      created_at: "2026-08-23T03:00:00Z",
      native_session_id: "native-awaiting", registered_session_id: null,
      identity_correlation: "awaiting_registration", instruction_delivery: "pending",
    },
    {
      launch_id: "launch-native-unreported", project_id: 1, state: "completed",
      created_at: "2026-08-23T02:00:00Z",
      native_session_id: null, registered_session_id: "registered-only",
      identity_correlation: "native_unreported", instruction_delivery: "pending",
      result_evidence: "raw secret evidence must not render",
    },
    {
      launch_id: "launch-correlation-failed", project_id: 1,
      created_at: "2026-08-23T01:00:00Z",
      state: "outcome_unknown", result_code: "identity_parse_failed",
      native_session_id: null, registered_session_id: null,
      identity_correlation: "correlation_failed",
      instruction_delivery: "not_delivered",
    },
  ];
  const byLaunchId = new Map(launches.map((launch) => [launch.launch_id, launch]));
  const client = {
    async call(request) {
      const shell = shellResult(request);
      if (shell) return shell;
      if (request.function === "session_control.launch.list") {
        return ok({
          operational: launches,
          operational_count: launches.length,
          history: [],
          history_matched_count: 0,
          next_cursor: null,
        });
      }
      if (request.function === "session_control.launch.get") {
        return ok({ launch: byLaunchId.get(request.payload.launch_id) });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t, "#/launches?project=1", client,
  );
  // Identity, delivery, and evidence live in the expanded record, which the
  // list fetches one row at a time.
  for (const row of byClass(root, "session-launch-row")) {
    allNodes(row).find(
      (node) => node.tagName === "BUTTON" && node.textContent === "Details",
    ).dispatchEvent(new Event("click"));
    await settle();
  }

  assert.deepEqual(
    byClass(root, "session-launch-correlation").map((node) => node.textContent),
    [
      "Identity matched",
      "Identity mismatch: native and registered sessions differ",
      "Awaiting registration",
      "Registered; native identity not reported",
      "Identity correlation failed: identity parse failed",
    ],
  );
  assert.deepEqual(
    byClass(root, "session-launch-delivery").map((node) => node.textContent),
    [
      "Launch instruction delivered",
      "Launch instruction delivery pending",
      "Launch instruction delivery pending",
      "Launch instruction delivery pending",
      "Launch instruction not delivered",
    ],
  );
  assert.match(
    byClass(root, "session-launch-identity")[0].textContent,
    /launch-matched → native session-matched → registered session-matched/,
  );
  const link = byClass(root, "session-result-link").find(
    (node) => node.textContent.includes("session-matched"),
  );
  assert.equal(link.href, "#/sessions/session-matched?project=1");
  const rendered = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(rendered, /adapter revision: adapter-v2/);
  for (const safeFact of [
    "native instruction sha256: sha256:safe-digest",
    "result code: native_created",
    "surface: codex-desktop",
    "duration ms: 9",
    "exit code: 0",
    "probe detail: model does not support effort max",
  ]) assert.match(rendered, new RegExp(safeFact));
  assert.match(
    byClass(root, "session-launch-model-request")[0].textContent,
    /gpt-5\.6-sol \(requested\).*XHIGH \(requested\).*1m \(requested\)/,
  );
  // The effective selection rides the compact row, not the expanded record.
  assert.match(
    byClass(root, "session-launch-summary")[0].textContent,
    /gpt-5\.6-sol.*XHIGH.*1m/,
  );
  assert.doesNotMatch(
    rendered,
    /secret-attestation|raw secret evidence|secret-token|secret-body|secret-argument|secret-stdout|secret-stderr/,
  );
  mounted.unmount();
});


test("registered-session drill-in uses the exact session lookup", async (t) => {
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      const shell = shellResult(request);
      if (shell) return shell;
      if (request.function === "sessions.list") {
        return ok({
          rows: [{
            session_id: "session-matched",
            liveness: "active",
            mode: "wait",
            executor: "codex",
            executor_surface: "codex-desktop",
            executor_version: "26.818.31338",
            model: "gpt-5.6-sol",
            actor_kind: "human",
            actor_label: "operator",
            activity_at: "2026-08-23T12:00:00Z",
            claims: [],
            messageability: {
              messageable: false,
              reason: "no_supported_hook_route",
            },
          }],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t, "#/sessions/session-matched?project=1", client,
  );

  // The app-wide steering-color roster (context.refreshSteeringGroupColors)
  // also calls sessions.list at boot, so match on session_id rather than
  // taking the first sessions.list call.
  const lookup = requests.find(
    (request) => request.function === "sessions.list" && request.payload?.session_id,
  );
  assert.deepEqual(lookup.payload, { project: "1", session_id: "session-matched" });
  assert.equal(byClass(root, "session-card").length, 1);
  assert.equal(
    byClass(root, "session-card")[0].getAttribute("data-session-id"),
    "session-matched",
  );
  // One is this view's own exact-session lookup; the other is the app-wide
  // steering-color roster refreshed once at boot (context.
  // refreshSteeringGroupColors), independent of which route is active.
  assert.equal(requests.filter(
    (request) => request.function === "sessions.list",
  ).length, 2);
  mounted.unmount();
});
