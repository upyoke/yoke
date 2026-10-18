import assert from "node:assert/strict";
import test from "node:test";
import { deferredRenderer } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_loader.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

function fixture() {
  const document = new FakeDocument();
  const host = document.createElement("div");
  const controller = new AbortController();
  const context = { document, signal: controller.signal, isMounted: () => true };
  let resolve;
  const module = new Promise((finish) => { resolve = finish; });
  return { host, context, controller, resolve, render: deferredRenderer(() => module, "screen") };
}

test("a deferred destination keeps loading visible and returns its rescope handle", async () => {
  const { host, context, resolve, render } = fixture();
  const handle = { rescope() {} };
  const pending = render(context, host, ["2"]);
  assert.match(host.textContent, /Loading screen/);
  resolve({ screen(actualContext, actualHost, scope) {
    assert.equal(actualContext, context);
    assert.deepEqual(scope, ["2"]);
    actualHost.textContent = "real screen";
    return handle;
  } });
  assert.equal(await pending, handle);
  assert.equal(host.textContent, "real screen");
});

test("navigation discards a module that finishes after its view was aborted", async () => {
  const { host, context, controller, resolve, render } = fixture();
  let called = false;
  const pending = render(context, host);
  controller.abort();
  resolve({ screen() { called = true; } });
  assert.equal(await pending, null);
  assert.equal(called, false);
});

test("unmount discards late rendering and a failed module reports recovery", async () => {
  const { host, context, resolve, render } = fixture();
  let called = false;
  const pending = render(context, host);
  context.isMounted = () => false;
  resolve({ screen() { called = true; } });
  await pending;
  assert.equal(called, false);
  context.isMounted = () => true;
  await deferredRenderer(() => Promise.reject(new Error("network")), "screen")(context, host);
  assert.match(host.textContent, /view_module_load_failed.*Reload to retry/);
});
