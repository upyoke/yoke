import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  presentSessionControlFailure,
  SessionControlFailure,
  sessionControlCall,
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

test("typed session-control errors redact storage detail and retain recovery", async () => {
  const context = {
    client: {
      call: async () => ({
        status: undefined,
        envelope: {
          success: false,
          error: {
            code: "internal_error",
            message: "SQLite database error: SELECT secret FROM launch_tokens",
            recovery_hint: "Refresh the page and try again.",
          },
        },
      }),
    },
  };
  let failure;
  try {
    await sessionControlCall(context, "session_control.launch.list");
  } catch (error) {
    failure = error;
  }

  assert.ok(failure instanceof SessionControlFailure);
  const text = presentSessionControlFailure(
    failure, "Session launches could not be loaded.",
  );
  assert.equal(text.includes("Refresh the page and try again."), true);
  assert.equal(/SQL|database|launch_tokens|HTTP undefined/i.test(text), false);
});

test("uncertain launches require reconciliation before retry", async (t) => {
  const requests = [];
  let reconciled = false;
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "session_control.launch.list") {
        return ok({
          launches: [{
            launch_id: "launch-uncertain",
            state: reconciled ? "failed" : "outcome_unknown",
            result_code: reconciled ? "late_native_reconciled" : "outcome_unknown",
            requested_surface: "codex-desktop",
            selected_surface: "codex-desktop",
            assigned_machine_id: "machine-1",
          }],
          count: 1,
        });
      }
      if (request.function === "session_control.launch.reconcile") {
        reconciled = true;
        return ok({ launch: { launch_id: "launch-uncertain", state: "failed" } });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(
    t, "#/sessions/launches?project=1", client,
  );

  assert.equal(button(root, "Retry").disabled, true);
  const text = allNodes(root).map((node) => node._textContent).join(" ");
  assert.equal(text.includes("The launch instruction was not delivered"), true);
  assert.equal(
    text.includes("Reconcile whether a native session exists before retrying"), true,
  );
  assert.equal(requests.some(
    (request) => request.function === "session_control.launch.retry",
  ), false);
  const nativeId = byClass(root, "session-launch-reconcile-id")[0];
  nativeId.value = "native-session-1";
  button(root, "Reconcile").dispatchEvent(new Event("click"));
  await settle();
  const reconcile = requests.find(
    (request) => request.function === "session_control.launch.reconcile",
  );
  assert.deepEqual(reconcile.payload, {
    launch_id: "launch-uncertain", observed_native_id: "native-session-1",
  });
  assert.equal(button(root, "Retry").disabled, false);
  assert.equal(requests.filter(
    (request) => request.function === "session_control.launch.list",
  ).length, 2);
  mounted.unmount();
});
