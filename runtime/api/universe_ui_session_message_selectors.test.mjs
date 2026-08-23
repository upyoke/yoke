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

test("message compose exposes every semantic anchor, filter, and exclusion", async (t) => {
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "session_control.message.list") {
        return ok({ messages: [], count: 0 });
      }
      if (request.function === "session_control.message.preview") {
        return ok({ recipients: [], recipient_count: 0, confirmation_token: "c1" });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions/messages?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  button(root, "Compose message").dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "session-selector-advanced").length, 1);
  assert.ok(allNodes(root).some(
    (node) => node.tagName === "SUMMARY" && node.textContent === "More targeting options",
  ));

  const values = {
    sessions: "session-1, session-2",
    items: "YOK-2363",
    epicTasks: "YOK-2363:4",
    processes: "FLEET-COMMS",
    projects: "yoke",
    executors: "codex claude",
    surfaces: "codex-desktop, claude-cli",
    roles: "worker",
    executionLanes: "DARIUS",
    worktrees: "YOK-2363-relay",
    machines: "studio",
    liveness: "active stale",
    exclusions: "session-2",
  };
  for (const [key, value] of Object.entries(values)) {
    byClass(root, `session-message-selector-${key}`)[0].value = value;
  }
  byClass(root, "session-message-selector-universe")[0].checked = true;
  byClass(root, "session-message-body")[0].value = "Test the complete selector.";
  button(root, "Preview recipients").dispatchEvent(new Event("click"));
  await settle();

  const preview = requests.find(
    (request) => request.function === "session_control.message.preview",
  );
  assert.deepEqual(preview.payload.selector, {
    universe: true,
    session_ids: ["session-1", "session-2"],
    item_refs: ["YOK-2363"],
    epic_tasks: ["YOK-2363:4"],
    process_keys: ["FLEET-COMMS"],
    projects: ["yoke"],
    executor_families: ["codex", "claude"],
    executor_surfaces: ["codex-desktop", "claude-cli"],
    work_roles: ["worker"],
    execution_lanes: ["DARIUS"],
    worktree_lanes: ["YOK-2363-relay"],
    machine_ids: ["studio"],
    liveness: ["active", "stale"],
    exclude_session_ids: ["session-2"],
  });
  mounted.unmount();
});
