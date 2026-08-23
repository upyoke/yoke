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

async function mountAt(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions/launches?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

test("launch fallback requires a visible opt-in and shows the selected surface", async (t) => {
  const requests = [];
  const relay = {
    relay_id: "machine:m1", machine_id: "m1", hostname: "studio",
    state: "active",
    surface_versions: {
      "codex-vscode": "0.148.0-alpha.15", "codex-cli": "0.148.0-alpha.15",
    },
    project_ids: [1],
  };
  const handlers = {
    "session_control.launch.list": () => ok({ launches: [], count: 0 }),
    "sessions.list": () => ok({ rows: [] }),
    "session_control.relay.list": () => ok({ relays: [relay], count: 1 }),
    "session_control.launch.preview": () => ok({
      outcome: "assigned_fallback", requested_surface: "codex-vscode",
      selected_surface: "codex-cli", fallback_used: true,
      launchable: true,
      eligible_relays: [{ ...relay, surface: "codex-cli" }],
      selected_relay: { ...relay, surface: "codex-cli" },
    }),
    "session_control.launch.create": () => ok({
      launch: {
        launch_id: "launch-fallback", state: "assigned",
        requested_surface: "codex-vscode", selected_surface: "codex-cli",
      },
      preview: {}, deduplicated: false,
    }),
  };
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      return handlers[request.function](request);
    },
  };
  const { root, mounted } = await mountAt(t, client);
  button(root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  const inputs = byClass(root, "session-control-input");
  inputs[1].value = "codex-vscode";
  inputs[4].value = "Use an explicitly approved same-family fallback.";
  const fallback = byClass(root, "session-control-checkbox")[0];
  fallback.checked = true;
  fallback.dispatchEvent(new Event("change"));
  button(root, "Preview launch").dispatchEvent(new Event("click"));
  await settle();

  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.ok(text.includes("Fallback selected codex-cli."));
  assert.ok(text.includes("m1 · codex-cli"));
  lastButton(root, "Create session").dispatchEvent(new Event("click"));
  await settle();
  const create = requests.find(
    (request) => request.function === "session_control.launch.create",
  );
  assert.equal(create.payload.executor_surface, "codex-vscode");
  assert.equal(create.payload.allow_surface_fallback, true);
  mounted.unmount();
});
