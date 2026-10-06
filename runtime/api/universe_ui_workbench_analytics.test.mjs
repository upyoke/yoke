import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

for (const mode of ["local", "selfhost", "hosted"]) {
  test(`${mode} workbench starts collection with no analytics control`, async (t) => {
    const originalFetch = globalThis.fetch;
    t.after(() => { globalThis.fetch = originalFetch; });
    globalThis.fetch = () => response(200, {});
    const originalWarn = console.warn;
    t.after(() => { console.warn = originalWarn; });
    console.warn = () => {};

    const documentNode = new FakeDocument();
    const configReads = [];
    // Collector setup is the workbench's own read; refuse it to keep the test offline.
    documentNode.defaultView.fetch = async (url) => {
      configReads.push(String(url));
      return { ok: false, status: 503 };
    };
    const root = documentNode.createElement("div");
    const mounted = mountUniverseApp(root, {
      client: injectedClient(mode),
      capabilities: { data: { portability: { mode } } },
    });
    t.after(() => mounted.unmount());
    await settle();

    assert.ok(configReads.includes("/api/events/config"));
    const nodes = allNodes(root);
    assert.ok(!nodes.some((node) => node.classList.contains("workbench-telemetry")));
    assert.ok(!nodes.some((node) => /analytics/i.test(node.textContent || "")
      && node.tagName === "BUTTON"));
  });
}
