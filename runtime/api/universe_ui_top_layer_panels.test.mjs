import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { claimingSession, workbenchClient } from "./universe_ui_workbench_test_support.mjs";

test("floating panels share manual top-layer disclosure and keep their DOM hosts", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient({
    "sessions.list": { rows: [claimingSession()] },
  }) });
  t.after(() => mounted.unmount());
  await settle();

  for (const className of [
    "onboarding-summary", "item-status-detail", "item-claimant-preview",
    "actor-menu", "header-search-overlay",
  ]) {
    const panels = byClass(root, className);
    assert.ok(panels.length, `${className} is mounted`);
    for (const panel of panels) {
      assert.equal(panel.getAttribute("popover"), "manual", className);
      assert.equal(panel.matches(":popover-open"), false, className);
    }
  }
  assert.equal(byClass(root, "onboarding-summary")[0].id, "onboarding-summary");
  const status = byClass(root, "item-status-pill")[0];
  const detail = byClass(root, "item-status-detail")[0];
  const chip = byClass(root, "item-claimant-mini")[0];
  const preview = byClass(root, "item-claimant-preview")[0];
  status.dispatchEvent(new Event("pointerenter"));
  assert.equal(detail.matches(":popover-open"), true);
  chip.dispatchEvent(new Event("pointerenter"));
  assert.equal(detail.matches(":popover-open"), false);
  assert.equal(status.getAttribute("aria-expanded"), "false");
  assert.equal(preview.matches(":popover-open"), true);
  assert.ok(chip.parentNode.contains(preview));
  const click = new Event("click", { bubbles: true });
  preview.dispatchEvent(click);
  assert.equal(click.cancelBubble, true, "panel clicks do not activate a tile");
  byClass(preview, "reveal-close")[0].dispatchEvent(new Event("click"));
  assert.equal(preview.matches(":popover-open"), false);
});
