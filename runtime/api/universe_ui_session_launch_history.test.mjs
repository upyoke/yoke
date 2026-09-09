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

async function mountAt(t, client, hash = "#/launches?project=1") {
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

test("the first view carries every actionable launch and a bounded history", async (t) => {
  const client = clientFor({
    "session_control.launch.list": () => page({
      operational: [launch("launch-stranded", {
        state: "outcome_unknown",
        result_code: "native_create_timed_out",
        created_at: "2026-01-01T00:00:00Z",
        completed_at: null,
      })],
      operational_count: 1,
      history: [launch("launch-recent")],
      history_matched_count: 412,
    }),
  });
  const { root, mounted } = await mountAt(t, client);

  assert.deepEqual(rowIds(root), ["launch-stranded", "launch-recent"]);
  const rendered = text(root);
  // An honest count says how many matched, never how many are on screen.
  assert.ok(rendered.includes("Needs attention · 1 unfinished or actionable"));
  assert.ok(rendered.includes("History · 1 of 412 matching loaded"));
  assert.ok(rendered.includes("outcome unknown (native create timed out)"));
  assert.ok(rendered.includes("Project yoke"));
  assert.ok(rendered.includes("not completed"));
  mounted.unmount();
});

test("Load more pages history forward and stops when the cursor runs out", async (t) => {
  const requests = [];
  const client = clientFor({
    "session_control.launch.list": (request) => {
      requests.push(request.payload);
      return request.payload.cursor
        ? page({
          history: [launch("launch-older", {
            created_at: "2026-08-22T01:00:00Z",
          })],
          history_matched_count: 2,
        })
        : page({
          history: [launch("launch-newer")],
          history_matched_count: 2,
          next_cursor: "cursor-1",
        });
    },
  });
  const { root, mounted } = await mountAt(t, client);

  assert.deepEqual(rowIds(root), ["launch-newer"]);
  button(root, "Load more").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(rowIds(root), ["launch-newer", "launch-older"]);
  assert.equal(requests[1].cursor, "cursor-1");
  assert.equal(requests[0].cursor, undefined);
  assert.equal(button(root, "Load more"), undefined);
  assert.ok(text(root).includes("History · 2 of 2 matching loaded"));
  mounted.unmount();
});

test("an all-project scope requests each project and labels every row", async (t) => {
  const requested = [];
  const client = clientFor(
    {
      "session_control.launch.list": (request) => {
        requested.push(request.payload.project);
        return page({
          history: [launch(`launch-${request.payload.project}`, {
            project: request.payload.project === "1" ? "yoke" : "platform",
            created_at: request.payload.project === "1"
              ? "2026-08-23T02:00:00Z"
              : "2026-08-23T03:00:00Z",
          })],
          history_matched_count: 1,
        });
      },
    },
    [
      { id: 1, slug: "yoke", name: "Yoke" },
      { id: 2, slug: "platform", name: "Platform" },
    ],
  );
  const { root, mounted } = await mountAt(t, client, "#/launches");

  assert.deepEqual(requested.sort(), ["1", "2"]);
  // Merged newest-first across projects, and each row says where it came from.
  assert.deepEqual(rowIds(root), ["launch-2", "launch-1"]);
  const rendered = text(root);
  assert.ok(rendered.includes("Project platform"));
  assert.ok(rendered.includes("Project yoke"));
  assert.ok(rendered.includes("History · 2 of 2 matching loaded"));
  mounted.unmount();
});

test("changing a filter resets paging and re-requests with the criterion", async (t) => {
  const requests = [];
  const client = clientFor({
    "session_control.launch.list": (request) => {
      requests.push(request.payload);
      return request.payload.state === "failed"
        ? page({
          operational: [launch("launch-failed", { state: "failed" })],
          operational_count: 1,
        })
        : page({
          history: [launch("launch-any")],
          history_matched_count: 9,
          next_cursor: "cursor-1",
        });
    },
  });
  const { root, mounted } = await mountAt(t, client);

  assert.ok(button(root, "Load more"));
  const state = filter(root, "state");
  state.value = "failed";
  state.dispatchEvent(new Event("change"));
  await settle();

  assert.deepEqual(requests.map((payload) => payload.state), [undefined, "failed"]);
  assert.equal(requests[1].cursor, undefined);
  assert.deepEqual(rowIds(root), ["launch-failed"]);
  // Paging state resets with the criteria it was computed against.
  assert.equal(button(root, "Load more"), undefined);
  assert.equal(state.value, "failed");
  mounted.unmount();
});

test("a superseded page response never overwrites the newer one", async (t) => {
  const pending = [];
  const client = clientFor({
    "session_control.launch.list": (request) => new Promise((resolve) => {
      pending.push(() => resolve(
        request.payload.state === "failed"
          ? page({
            operational: [launch("launch-failed", { state: "failed" })],
            operational_count: 1,
          })
          : page({ history: [launch("launch-stale")], history_matched_count: 1 }),
      ));
    }),
  });
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/launches?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const state = filter(root, "state");
  state.value = "failed";
  state.dispatchEvent(new Event("change"));
  await settle();
  // The newer request answers first; the superseded one answers afterwards.
  pending[1]();
  await settle();
  pending[0]();
  await settle();

  assert.deepEqual(rowIds(root), ["launch-failed"]);
  mounted.unmount();
});
