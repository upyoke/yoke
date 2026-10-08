import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, response, settle, byClass } from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

test("ready cards omit raw dispatch commands even from an older serving response", async (t) => {
  const original = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = original; });
  const document = new FakeDocument();
  document.defaultView.location.href = "/frontier?project=1";
  document.defaultView.fetch = globalThis.fetch;
  const root = document.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient() });
  await settle();
  const ready = byClass(root, "work-band-ready")[0];
  assert.ok(ready);
  assert.doesNotMatch(ready.textContent, /yoke (implement|dash|conduct)/);
  assert.equal(byClass(ready, "work-item-card-meta").length, 0);
  mounted.unmount();
});
