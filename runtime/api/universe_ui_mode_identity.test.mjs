import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";

for (const [mode, footer, actor] of [
  ["local", "local: reachable here only", "local actor"],
  ["self-host", "self-hosted universe", "actor unavailable"],
  ["hosted", "hosted universe", null],
]) {
  test(`${mode} shell uses its mode's universe and missing-actor labels`, async (t) => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = () => response(200, {});
    t.after(() => { globalThis.fetch = originalFetch; });
    const documentNode = new FakeDocument();
    documentNode.defaultView.fetch = () => response(200, {});
    const root = documentNode.createElement("div");
    const client = {
      async call(request) {
        if (request.function === "profile.get") {
          return { status: 403, envelope: { success: false } };
        }
        const result = request.function === "organizations.get"
          ? { name: "Team" } : { rows: [] };
        return { status: 200, envelope: { success: true, result } };
      },
    };
    const mounted = mountUniverseApp(root, {
      client, capabilities: { data: { portability: { mode } } },
    });
    t.after(() => mounted.unmount());
    await settle();
    assert.equal(byClass(root, "app-footer-environment")[0].textContent, footer);
    const names = byClass(root, "actor-name");
    if (actor === null) assert.equal(names.length, 0);
    else assert.equal(names[0].textContent, actor);
  });
}
