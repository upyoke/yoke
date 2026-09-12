// What the content area holds before a route can render, what it stops
// waiting on to get there, and what happens to a screen whose page went to
// sleep. Three behaviors, one subject: the frame around live data staying
// honest about what it does and does not have yet.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  createPageRevisit,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_page_revisit.js";
import {
  routeLoadingLine,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_route_loading.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => Promise.resolve({
    ok: true, status: 200, text: () => Promise.resolve(""),
    json: () => Promise.resolve({}),
  });
}

// Answers every read the mount and the Projects screen make. `pending` names
// functions whose promise is left hanging, which is how a slow or stuck read
// is expressed here.
function mountClient({ pending = [], failing = [] } = {}) {
  const requests = [];
  return {
    requests,
    call(request) {
      requests.push(request.function);
      if (pending.includes(request.function)) return new Promise(() => {});
      if (failing.includes(request.function)) {
        return Promise.resolve({
          status: 500,
          envelope: { success: false, error: { message: "unavailable" } },
        });
      }
      switch (request.function) {
        case "projects.list":
          return Promise.resolve(ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] }));
        case "ui_preferences.screen_selection.list":
          return Promise.resolve(ok({ views: {} }));
        default:
          return Promise.resolve(ok({ rows: [] }));
      }
    },
  };
}

async function mountAt(hash, client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  return { documentNode, mounted, root };
}

test("the pending content area carries one announced line, not a skeleton", () => {
  const documentNode = new FakeDocument();
  const line = routeLoadingLine(documentNode);
  assert.equal(line.textContent, "Loading…");
  assert.equal(line.getAttribute("role"), "status");
  assert.equal(line.getAttribute("aria-busy"), "true");
  // One node: no placeholder blocks standing in for a layout the app has
  // not resolved yet.
  assert.equal(line.children.length, 0);
});

test("the shell paints the line immediately and replaces it on first render", async (t) => {
  stubFetch(t);
  const client = mountClient();
  const { root, mounted } = await mountAt("#/projects", client);

  // Synchronously after mount — before any read can have resolved.
  assert.equal(byClass(root, "route-loading").length, 1);
  // And the shell around it is already real, so the line marks the one
  // region that is not.
  assert.equal(byClass(root, "topbar").length, 1);
  assert.ok(byClass(root, "nav-link").length > 0);

  await settle();
  await settle();
  assert.equal(byClass(root, "route-loading").length, 0);
  assert.equal(byClass(root, "panel").length > 0, true);
  mounted.unmount();
});

test("a failed roster read replaces the line with its error, never leaves it spinning", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt(
    "#/projects", mountClient({ failing: ["projects.list"] }),
  );
  await settle();
  await settle();

  assert.equal(byClass(root, "route-loading").length, 0);
  assert.match(byClass(root, "error-banner")[0].textContent, /Projects could not be loaded/);
  mounted.unmount();
});

test("a stuck steering-color read no longer holds the first content paint", async (t) => {
  stubFetch(t);
  // `sessions.list` here is the steering-group roster, which only tints
  // cards. It never resolves, and the screen still paints.
  const client = mountClient({ pending: ["sessions.list"] });
  const { root, mounted } = await mountAt("#/projects", client);
  await settle();
  await settle();

  assert.equal(byClass(root, "route-loading").length, 0);
  assert.equal(byClass(root, "panel").length > 0, true);
  assert.ok(client.requests.includes("sessions.list"));
  mounted.unmount();
});

function revisitHarness() {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const host = documentNode.createElement("div");
  root.appendChild(host);
  let mountedFlag = true;
  const revisit = createPageRevisit(documentNode, root, () => mountedFlag);
  const calls = [];
  revisit.subscribe(host, () => { calls.push("refresh"); });
  return {
    calls,
    documentNode,
    host,
    revisit,
    root,
    unmount: () => { mountedFlag = false; },
    windowNode: documentNode.defaultView,
  };
}

test("returning to the foreground re-reads once, however many events fire", async () => {
  const harness = revisitHarness();

  harness.documentNode.dispatchEvent(new Event("visibilitychange"));
  harness.windowNode.dispatchEvent(new Event("focus"));
  harness.documentNode.dispatchEvent(new Event("visibilitychange"));
  await settle();
  // One return, one read: visibilitychange and focus both fire on a single
  // wake, and re-reading per event would triple every recovery.
  assert.deepEqual(harness.calls, ["refresh"]);
  harness.revisit.dispose();
});

test("a page on its way out of the foreground re-reads nothing", async () => {
  const harness = revisitHarness();
  harness.documentNode.visibilityState = "hidden";

  harness.documentNode.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.deepEqual(harness.calls, []);
  harness.revisit.dispose();
});

test("a screen the router replaced drops out instead of spending a read", async () => {
  const harness = revisitHarness();
  harness.root.replaceChildren();

  harness.documentNode.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.deepEqual(harness.calls, []);
  harness.revisit.dispose();
});

test("an unmounted app and a disposed revisit both go quiet", async () => {
  const harness = revisitHarness();
  harness.unmount();
  harness.documentNode.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.deepEqual(harness.calls, []);

  const second = revisitHarness();
  second.revisit.dispose();
  second.documentNode.dispatchEvent(new Event("visibilitychange"));
  second.windowNode.dispatchEvent(new Event("focus"));
  await settle();
  assert.deepEqual(second.calls, []);
  assert.equal(second.windowNode.listenerCounts.get("focus"), 0);
  harness.revisit.dispose();
});

test("Sessions and Machines re-read their own live data on the return", async (t) => {
  stubFetch(t);
  for (const [hash, expected] of [
    ["#/sessions?project=1", "session_control.relay.list"],
    ["#/machines", "machine.list"],
  ]) {
    const client = mountClient();
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = hash;
    const root = documentNode.createElement("div");
    const mounted = mountUniverseApp(root, { client });
    await settle();
    await settle();
    const before = client.requests.filter((name) => name === expected).length;
    assert.ok(before > 0, `${hash} never read ${expected}`);

    documentNode.dispatchEvent(new Event("visibilitychange"));
    await settle();
    await settle();
    // The screen asked again, in place: the pre-sleep snapshot is what the
    // return exists to replace.
    assert.ok(
      client.requests.filter((name) => name === expected).length > before,
      `${hash} did not re-read ${expected} on the return`,
    );
    mounted.unmount();
  }
});
