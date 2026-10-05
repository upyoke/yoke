import assert from "node:assert/strict";
import test from "node:test";
import { readFile, readdir } from "node:fs/promises";
import { qaPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_primitives.js";
import { workflowPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_view_primitives.js";
import { secretPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_detail_panels.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const root = new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url);
test("descriptive section captions have no renderer or styling on any page", async () => {
  for (const name of await readdir(root)) {
    if (!/\.(js|css)$/.test(name)) continue;
    assert.doesNotMatch(await readFile(new URL(name, root), "utf8"), /qa-panel-context|panel-hint/, name);
  }
  const document = new FakeDocument();
  const qa = qaPanel(document, "Test plans", 2);
  assert.equal(qa.root.children[0].textContent, "Test plans· 2");
  const workflow = workflowPanel(document, "Stages", { version: 3 });
  assert.match(workflow.panel.children[0].textContent, /Stagescurrent · v3/);
  const secrets = secretPanel(document, { secrets: [] });
  assert.equal(byClass(secrets, "panel-hint").length, 0);
});
