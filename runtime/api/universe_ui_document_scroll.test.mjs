import assert from "node:assert/strict";
import test from "node:test";
import { attachDocumentScroll } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_document_scroll.js";

function fixture() {
  const window = new EventTarget();
  let frame, resize, disconnected = false;
  let available = 0;
  window.history = { state: { host: "preserved" }, scrollRestoration: "auto",
    replaceState(state) { this.state = state; } };
  window.scrollX = 0;
  window.scrollY = 0;
  window.scrollTo = (x, y) => { window.scrollX = x; window.scrollY = Math.min(y, available); };
  window.requestAnimationFrame = (callback) => { frame = callback; return 1; };
  window.cancelAnimationFrame = () => { frame = null; };
  window.ResizeObserver = class {
    constructor(callback) { resize = callback; }
    observe() {}
    disconnect() { disconnected = true; }
  };
  const dispose = attachDocumentScroll({}, window);
  return { window, dispose, disconnected: () => disconnected,
    grow(height) { available = height; resize(); },
    tick() { const callback = frame; frame = null; callback?.(); },
    visit(state) {
      window.history.state = state;
      const event = new Event("popstate"); event.state = state;
      window.dispatchEvent(event);
    } };
}

test("Back restores the history entry once asynchronous content can hold it", () => {
  const f = fixture();
  f.grow(1000); f.tick();
  f.window.scrollTo(0, 600); f.window.dispatchEvent(new Event("scroll"));
  const saved = f.window.history.state;
  assert.equal(saved.host, "preserved");
  f.visit(null); f.tick();
  assert.equal(f.window.scrollY, 0);
  f.grow(0); f.visit(saved); f.tick();
  f.window.dispatchEvent(new Event("scroll"));
  assert.equal(f.window.history.state, saved);
  f.grow(1000); f.tick();
  assert.equal(f.window.scrollY, 600);
  f.dispose();
  assert.equal(f.window.history.scrollRestoration, "auto");
  assert.equal(f.disconnected(), true);
});

test("reader input cancels a pending position rather than jumping later", () => {
  const f = fixture();
  f.visit({ universeDocumentScroll: { x: 0, y: 600 } }); f.tick();
  f.window.dispatchEvent(new Event("wheel"));
  f.grow(1000); f.tick();
  assert.equal(f.window.scrollY, 0);
  f.dispose();
});
