import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
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


function control(root, label) {
  return allNodes(root).find(
    (node) => node.tagName === "LABEL" && node.children[0]?.textContent === label,
  )?.children[1];
}


test("launch dialog previews and creates one explicit model selection", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const requests = [];
  const relay = {
    relay_id: "machine:m1",
    machine_id: "m1",
    hostname: "studio",
    state: "active",
    surface_versions: { "claude-cli": "2.1.259" },
    project_ids: [1],
  };
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "session_control.launch.list") {
        return ok({ launches: [], count: 0 });
      }
      if (request.function === "session_control.relay.list") {
        return ok({ relays: [relay], count: 1 });
      }
      if (request.function === "session_control.launch.preview") {
        return ok({
          outcome: "assigned",
          requested_surface: "claude-cli",
          requested_model: request.payload.model,
          requested_reasoning_effort: request.payload.reasoning_effort,
          requested_context_window_tokens: request.payload.context_window_tokens,
          selected_surface: "claude-cli",
          fallback_used: false,
          launchable: true,
          eligible_relays: [relay],
          selected_relay: relay,
        });
      }
      if (request.function === "session_control.launch.create") {
        return ok({ launch: { launch_id: "launch-1", state: "assigned" } });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/machines?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();

  button(root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  control(root, "Work item").value = "YOK-1";
  control(root, "Requested model (verified after launch)").value =
    "claude-opus-4-8";
  control(root, "Requested reasoning effort").value = "max";
  control(root, "Requested context window (tokens)").value = "1000000";
  control(root, "Optional extras after the composed mandate").value =
    "Run the bounded task.";
  button(root, "Preview launch").dispatchEvent(new Event("click"));
  await settle();

  const preview = requests.find(
    (request) => request.function === "session_control.launch.preview",
  );
  assert.equal(preview.payload.model, "claude-opus-4-8");
  assert.equal(preview.payload.reasoning_effort, "max");
  assert.equal(preview.payload.context_window_tokens, 1_000_000);
  assert.match(
    allNodes(root).filter(
      (node) => node.classList.contains("session-control-status"),
    ).at(-1).textContent,
    /served facts settle independently/,
  );

  allNodes(root).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Create session",
  ).at(-1).dispatchEvent(new Event("click"));
  await settle();
  const create = requests.find(
    (request) => request.function === "session_control.launch.create",
  );
  assert.equal(create.payload.model, "claude-opus-4-8");
  assert.equal(create.payload.reasoning_effort, "max");
  assert.equal(create.payload.context_window_tokens, 1_000_000);
  mounted.unmount();
});
