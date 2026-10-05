import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, injectedClient, response, settle } from "./universe_ui_dom_test_support.mjs";

async function mountDashboard(t) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = originalFetch; });
  const document = new FakeDocument();
  const window = document.defaultView;
  const writes = [];
  window.location.href = "/members";
  window.history = {
    state: { __NA: true, host: "preserved" },
    scrollRestoration: "auto",
    pushState(...args) { writes.push(["push", ...args]); },
    replaceState(...args) { writes.push(["replace", ...args]); },
  };
  window.scrollX = 0;
  window.scrollY = 0;
  window.requestAnimationFrame = () => 1;
  window.cancelAnimationFrame = () => {};
  window.ResizeObserver = class { observe() {} disconnect() {} };
  const root = document.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: injectedClient("host"),
    sections: { members: document.createElement("section") },
  });
  t.after(() => mounted.unmount());
  await settle();
  writes.length = 0;
  return { window, writes, mounted };
}

test("scrolling the mounted dashboard document never writes history", async (t) => {
  const { window, writes } = await mountDashboard(t);
  const state = window.history.state;
  for (let y = 0; y < 250; y += 1) {
    window.scrollY = y;
    window.dispatchEvent(new Event("scroll"));
  }
  assert.deepEqual(writes, []);
  assert.equal(window.history.state, state);
});

test("the dashboard leaves native scroll restoration enabled throughout its mount", async (t) => {
  const { window, mounted } = await mountDashboard(t);
  assert.equal(window.history.scrollRestoration, "auto");
  window.dispatchEvent(new Event("scroll"));
  window.dispatchEvent(new Event("popstate"));
  assert.equal(window.history.scrollRestoration, "auto");
  mounted.unmount();
  assert.equal(window.history.scrollRestoration, "auto");
});
