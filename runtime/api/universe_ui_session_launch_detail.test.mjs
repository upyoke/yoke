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

function filter(root, key) {
  return allNodes(root).find(
    (node) => node.getAttribute("data-launch-filter") === key,
  );
}

function rowIds(root) {
  return byClass(root, "session-launch-row").map(
    (node) => node.getAttribute("data-launch-id"),
  );
}

function text(root) {
  return allNodes(root).map((node) => node._textContent).join(" ");
}

function launch(id, overrides = {}) {
  return {
    launch_id: id,
    project_id: 1,
    project: "yoke",
    state: "succeeded",
    requested_surface: "codex-cli",
    selected_surface: "codex-cli",
    assigned_machine_id: "machine-1",
    created_at: "2026-08-23T01:00:00Z",
    completed_at: "2026-08-23T01:05:00Z",
    ...overrides,
  };
}

function page(overrides = {}) {
  return ok({
    operational: [],
    operational_count: 0,
    history: [],
    history_matched_count: 0,
    next_cursor: null,
    ...overrides,
  });
}

async function mountAt(t, client, hash = "#/machines?project=1") {
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

function clientFor(handlers, projects = [{ id: 1, slug: "yoke", name: "Yoke" }]) {
  return {
    async call(request) {
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") return ok({ rows: projects });
      if (request.function === "sessions.list") return ok({ rows: [] });
      if (request.function === "session_control.relay.list") {
        return ok({ relays: [], count: 0 });
      }
      const handler = handlers[request.function];
      if (!handler) throw new Error(`unexpected function ${request.function}`);
      return handler(request);
    },
  };
}

test("expanding one row fetches its record and keeps its actions", async (t) => {
  const requests = [];
  const client = clientFor({
    "session_control.launch.list": () => page({
      operational: [launch("launch-failed", { state: "failed" })],
      operational_count: 1,
    }),
    "session_control.launch.get": (request) => {
      requests.push(request.payload.launch_id);
      return ok({
        launch: launch("launch-failed", {
          state: "failed",
          identity_correlation: "registration_failed",
          instruction_delivery: "delivered",
          launching_at: "2026-08-23T01:02:00Z",
          awaiting_registration_at: "2026-08-23T01:03:00Z",
        }),
      });
    },
  });
  const { root, mounted } = await mountAt(t, client);

  // Nothing is fetched for a collapsed row.
  assert.deepEqual(requests, []);
  assert.equal(button(root, "Retry"), undefined);
  button(root, "Details").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(requests, ["launch-failed"]);
  assert.equal(button(root, "Retry").disabled, false);
  const expanded = text(root);
  assert.ok(expanded.includes("Session registration failed"));
  // The timeline is detail-only: the compact row never carries these stamps.
  assert.ok(expanded.includes("launching:"));
  assert.ok(expanded.includes("awaiting registration:"));
  assert.ok(expanded.includes("2026-08-23 01:02 UTC"));
  button(root, "Hide details").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(button(root, "Retry"), undefined);
  mounted.unmount();
});

test("a retry reloads the list and refreshes the open record", async (t) => {
  let retried = false;
  const listed = [];
  const client = clientFor({
    "session_control.launch.list": () => {
      listed.push(retried);
      return page({
        operational: [launch("launch-failed", {
          state: retried ? "assigned" : "failed",
        })],
        operational_count: 1,
      });
    },
    "session_control.launch.get": () => ok({
      launch: launch("launch-failed", { state: retried ? "assigned" : "failed" }),
    }),
    "session_control.launch.retry": () => {
      retried = true;
      return ok({ launch: launch("launch-failed", { state: "assigned" }) });
    },
  });
  const { root, mounted } = await mountAt(t, client);
  button(root, "Details").dispatchEvent(new Event("click"));
  await settle();

  button(root, "Retry").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(listed, [false, true]);
  assert.ok(text(root).includes("launch-failed retried."));
  // The reopened record reflects the state the mutation produced.
  assert.equal(button(root, "Cancel").disabled, false);
  assert.equal(button(root, "Retry").disabled, true);
  mounted.unmount();
});

test("an empty scope and a failed load each say what to do next", async (t) => {
  const empty = await mountAt(t, clientFor({
    "session_control.launch.list": () => page(),
  }));
  const emptyText = text(empty.root);
  assert.ok(emptyText.includes("No unfinished or actionable launches."));
  assert.ok(emptyText.includes("No completed launches yet."));
  empty.mounted.unmount();

  const broken = await mountAt(t, clientFor({
    "session_control.launch.list": () => ({
      status: 403,
      envelope: {
        success: false,
        error: {
          code: "permission_denied",
          message: "project operator required",
        },
      },
    }),
  }));
  assert.ok(text(broken.root).includes(
    "You do not have permission for that session-control action.",
  ));
  broken.mounted.unmount();
});

test("a failed detail fetch names the failure and its recovery", async (t) => {
  const client = clientFor({
    "session_control.launch.list": () => page({
      operational: [launch("launch-failed", { state: "failed" })],
      operational_count: 1,
    }),
    "session_control.launch.get": () => ({
      status: 404,
      envelope: {
        success: false,
        error: { code: "not_found", message: "launch is gone" },
      },
    }),
  });
  const { root, mounted } = await mountAt(t, client);
  button(root, "Details").dispatchEvent(new Event("click"));
  await settle();

  const rendered = text(root);
  assert.ok(rendered.includes("That session-control record is no longer available."));
  assert.ok(rendered.includes("Refresh the page before choosing another action."));
  mounted.unmount();
});
