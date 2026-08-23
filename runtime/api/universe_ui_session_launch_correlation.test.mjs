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
      native_session_id: "session-matched", registered_session_id: "session-matched",
      result_code: "native_created",
      result_evidence: {
        adapter_revision: "adapter-v2",
        native_instruction_sha256: "sha256:safe-digest",
        result_code: "native_created",
        surface: "codex-desktop",
        duration_ms: 9,
        exit_code: 0,
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
      native_session_id: "native-a", registered_session_id: "registered-b",
    },
    {
      launch_id: "launch-awaiting", project_id: 1, state: "awaiting_registration",
      native_session_id: "native-awaiting", registered_session_id: null,
    },
    {
      launch_id: "launch-native-unreported", project_id: 1, state: "completed",
      native_session_id: null, registered_session_id: "registered-only",
      result_evidence: "raw secret evidence must not render",
    },
  ];
  const client = {
    async call(request) {
      const shell = shellResult(request);
      if (shell) return shell;
      if (request.function === "session_control.launch.list") {
        return ok({ launches, count: launches.length });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t, "#/sessions/launches?project=1", client,
  );

  assert.deepEqual(
    byClass(root, "session-launch-correlation").map((node) => node.textContent),
    [
      "Identity matched",
      "Identity mismatch: native and registered sessions differ",
      "Awaiting registration",
      "Registered; native identity not reported",
    ],
  );
  assert.match(
    byClass(root, "session-launch-identity")[0].textContent,
    /launch-matched → native session-matched → registered session-matched/,
  );
  const link = byClass(root, "session-result-link").find(
    (node) => node.textContent.includes("session-matched"),
  );
  assert.equal(link.href, "#/sessions/roster/session-matched?project=1");
  const rendered = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(rendered, /adapter revision: adapter-v2/);
  for (const safeFact of [
    "native instruction sha256: sha256:safe-digest",
    "result code: native_created",
    "surface: codex-desktop",
    "duration ms: 9",
    "exit code: 0",
  ]) assert.match(rendered, new RegExp(safeFact));
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
    t, "#/sessions/roster/session-matched?project=1", client,
  );

  const lookup = requests.find((request) => request.function === "sessions.list");
  assert.deepEqual(lookup.payload, { project: "1", session_id: "session-matched" });
  assert.equal(byClass(root, "session-card").length, 1);
  assert.equal(
    byClass(root, "session-card")[0].getAttribute("data-session-id"),
    "session-matched",
  );
  assert.equal(requests.filter(
    (request) => request.function === "sessions.list",
  ).length, 1);
  mounted.unmount();
});
