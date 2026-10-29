import test from "node:test";
import assert from "node:assert/strict";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, response, settle, visibleText, byClass } from "./universe_ui_dom_test_support.mjs";

for (const detail of [false, true]) {
  test(`feedback ${detail ? "detail" : "roster"} works without any project`, async (t) => {
    const previous = globalThis.fetch;
    t.after(() => { globalThis.fetch = previous; });
    globalThis.fetch = () => response(200, {});
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.href = detail ? "/ouroboros/9" : "/ouroboros";
    const root = documentNode.createElement("div");
    const calls = [];
    const entry = { id: 9, category: "observation", project: "", preview: "Unscoped evidence", body: "Unscoped evidence" };
    const client = { async call(request) {
      calls.push(request);
      const result = request.function === "projects.list" ? { rows: [] }
        : request.function === "ouroboros.field_note.list" ? { entries: [entry], matching_count: 1, next_cursor: null }
        : request.function === "ouroboros.field_note.get" ? { entry } : { name: "Universe" };
      return { status: 200, envelope: { success: true, result } };
    } };
    const mounted = mountUniverseApp(root, { client });
    await settle();
    assert.match(visibleText(root, " "), /Unscoped evidence/);
    const read = calls.find(call => call.function === `ouroboros.field_note.${detail ? "get" : "list"}`);
    assert.ok(read);
    assert.equal("project" in read.payload, false);
    if (detail) assert.equal(read.payload.entry_id, 9);
    else {
      assert.equal(read.payload.scope, "universe");
      assert.ok(byClass(root, "row-link").some(node => node.href === "/ouroboros/9"));
    }
    mounted.unmount();
  });
}
