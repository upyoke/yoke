import assert from "node:assert/strict";
import test from "node:test";
import { waiverDialog } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_plan_actions.js";
import { terminalizationDialog } from "../../packages/yoke-core/src/yoke_core/ui/static/deployment_run_terminalization_dialog.js";
import { renderPacksView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_packs.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

function key(document, value, shiftKey = false) {
  const event = new Event("keydown", { cancelable: true });
  Object.defineProperties(event, { key: { value }, shiftKey: { value: shiftKey } });
  document.defaultView.dispatchEvent(event);
}

test("waiver and terminalization dialogs focus, contain, restore, and guard pending actions", async () => {
  for (const create of [
    (context, done) => waiverDialog(context, { case_key: "case", last_result: { requirement_id: 8 } }, done),
    (context, done) => terminalizationDialog(context, { id: "run-example", status: "executing" }, done),
  ]) {
    const document = new FakeDocument();
    const main = document.createElement("main");
    const opener = document.createElement("button");
    main.appendChild(opener);
    opener.focus();
    let finish;
    const context = { document, client: { call: () => new Promise((resolve) => { finish = resolve; }) } };
    const overlay = create(context, () => {});
    main.appendChild(overlay);
    await settle();
    const textarea = allNodes(overlay).find((node) => node.tagName === "TEXTAREA");
    assert.equal(document.activeElement, textarea);
    const controls = allNodes(overlay).filter((node) => ["BUTTON", "TEXTAREA", "SELECT"].includes(node.tagName));
    controls.at(-1).focus();
    key(document, "Tab");
    assert.equal(document.activeElement, controls[0]);
    key(document, "Tab", true);
    assert.equal(document.activeElement, controls.at(-1));
    textarea.value = "Reviewed reason";
    byClass(overlay, "primary")[0].dispatchEvent(new Event("click"));
    key(document, "Escape");
    overlay.dispatchEvent(new Event("click"));
    assert.equal(overlay.parentNode, main);
    finish({ status: 200, envelope: { success: true, result: {} } });
    await settle();
    assert.equal(overlay.parentNode, null);
    assert.equal(document.activeElement, opener);
    main.appendChild(create(context, () => {}));
    await settle();
    key(document, "Escape");
    assert.equal(main.children.length, 1);
    assert.equal(document.activeElement, opener);
  }
});

test("expired repository reports do not invent Pack upgrades", async () => {
  const document = new FakeDocument();
  const main = document.createElement("main");
  renderPacksView({ document, isMounted: () => true, projects: () => [{ id: 1 }], client: {
    async call() { return { status: 200, envelope: { success: true, result: {
      project_id: 1, project_slug: "demo", repository_report: { fresh: false },
      packs: [
        { slug: "current", status: "stale", installed_version: "1.0", latest_version: "1.0",
          stale_reasons: ["repository_report_expired"] },
        { slug: "upgrade", status: "stale", installed_version: "1.0", latest_version: "1.1",
          stale_reasons: ["update_available", "repository_report_expired"] },
      ],
    } } }; },
  } }, main, null);
  await settle();
  assert.deepEqual(byClass(main, "pill").map((node) => node.textContent), ["report out of date", "update available"]);
  assert.deepEqual(byClass(main, "pack-preview-action").map((node) => node.textContent), ["Inspect update"]);
});
