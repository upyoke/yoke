import assert from "node:assert/strict";
import test from "node:test";
import { renderMachineDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machine_detail.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
const ok = (result) => ({ status: 200, envelope: { success: true, result } });

test("detail retirement retains a retryable action after network rejection", async () => {
  const document = new FakeDocument();
  document.defaultView.confirm = () => true;
  const main = document.createElement("main");
  let reject;
  const pending = new Promise((resolve, fail) => { reject = fail; });
  let retireCalls = 0;
  const detail = { machine: { machine_id: "m1", name: "Studio" }, token: {}, projects: [], harnesses: [] };
  renderMachineDetail({ document, isMounted: () => true, client: { async call(request) {
    if (request.function === "machine.detail") return ok(detail);
    if (++retireCalls === 1) return pending;
    detail.machine.retired_at = "2026-10-02T12:00:00Z";
    return ok({});
  } } }, main, null, "m1");
  await settle();
  const retire = byClass(main, "machine-retire")[0];
  retire.dispatchEvent(new Event("click"));
  retire.dispatchEvent(new Event("click"));
  assert.equal(retireCalls, 1);
  assert.equal(retire.disabled, true);
  reject(new Error("Network unavailable"));
  await settle();
  assert.match(main.textContent, /temporarily unavailable.*Try Retire again/);
  assert.equal(retire.disabled, false);
  retire.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(retireCalls, 2);
  assert.equal(byClass(main, "machine-retire").length, 0);
  assert.match(main.textContent, /Retired/);
});
