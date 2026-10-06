import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";
import { mountBuildUpdate } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_build_update.js";

const settle = () => new Promise(setImmediate);
function fixture({ loaded = "old", pathname = "/", visibility = "visible", answers = ["old"] } = {}) {
  const doc = new FakeDocument();
  doc.visibilityState = visibility;
  const body = doc.createElement("div"), main = doc.createElement("main");
  body.appendChild(main);
  const requests = [];
  let tick, cleared = false, reloads = 0;
  const windowNode = Object.assign(new EventTarget(), {
    AbortController, setTimeout, clearTimeout,
    location: { pathname, reload() { reloads++; } },
    setInterval(callback, delay) { assert.equal(delay, 60_000); tick = callback; return 1; },
    clearInterval(id) { assert.equal(id, 1); cleared = true; },
    async fetch(url, options) {
      requests.push({ url, options });
      const answer = answers.shift();
      if (answer instanceof Error) throw answer;
      return answer instanceof Response ? answer : new Response(answer ?? "");
    },
  });
  const dispose = mountBuildUpdate(main, windowNode, { runtimeIdentity: { build: loaded } });
  return { doc, body, main, windowNode, requests, dispose,
    tick: () => tick(), status: body.children[0], banner: () => body.children[0].children[0],
    cleared: () => cleared, reloads: () => reloads };
}

test("only a changed build reveals a persistent banner and manual full reload", async () => {
  const f = fixture({ answers: ["old", "new", "old"] });
  await settle();
  assert.equal(f.status.children.length, 0);
  assert.equal(f.status.getAttribute("role"), "status");
  assert.notEqual(f.status.hidden, true);
  const region = f.status;
  f.windowNode.dispatchEvent(new Event("focus"));
  await settle();
  assert.equal(f.status.children.length, 1);
  assert.equal(f.body.children[0], region);
  assert.notEqual(region.hidden, true);
  assert.equal(f.status.getAttribute("role"), "status");
  assert.equal(f.banner().children[0].textContent, "A new version of Yoke is available.");
  assert.equal(f.reloads(), 0);
  f.main.replaceChildren(f.doc.createElement("section"));
  f.tick();
  await settle();
  assert.equal(f.status.children.length, 1);
  assert.equal(f.requests.length, 2);
  f.banner().children[1].dispatchEvent(new Event("click"));
  assert.equal(f.reloads(), 1);
  f.dispose();
  assert.equal(f.cleared(), true);
  assert.deepEqual(f.body.children, [f.main]);
  f.windowNode.dispatchEvent(new Event("focus"));
  f.doc.dispatchEvent(new Event("visibilitychange"));
  f.tick();
  assert.equal(f.requests.length, 2);
});

test("empty, failed and refused reads stay silent and later visible checks retry", async () => {
  const f = fixture({ answers: ["", new Error("offline"), new Response("new", { status: 503 }), "new"] });
  await settle();
  assert.equal(f.status.children.length, 0);
  f.tick(); await settle();
  assert.equal(f.status.children.length, 0);
  f.tick(); await settle();
  assert.equal(f.status.children.length, 0);
  f.doc.visibilityState = "hidden";
  f.doc.dispatchEvent(new Event("visibilitychange"));
  assert.equal(f.requests.length, 3);
  f.doc.visibilityState = "visible";
  f.doc.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(f.status.children.length, 1);
  f.dispose();
});

test("hosted dashboards without a loaded identity establish a baseline at the site root", async () => {
  const f = fixture({ loaded: "", pathname: "/orgs/acme/sessions", answers: ["", " old\n", "old", "new"] });
  await settle();
  for (let i = 0; i < 2; i++) { f.tick(); await settle(); assert.equal(f.status.children.length, 0); }
  f.tick(); await settle();
  assert.equal(f.status.children.length, 1);
  assert.ok(f.requests.every(r => r.url === "/served-build"));
  assert.equal(f.requests[0].options.cache, "no-store");
  assert.equal(f.requests[0].options.credentials, "same-origin");
  f.dispose();
});

test("unmount aborts an in-flight read and ignores a late changed response", async () => {
  const f = fixture();
  await settle();
  let resolve;
  f.windowNode.fetch = (_url, options) => {
    f.requests.push({ options });
    return new Promise(done => { resolve = done; });
  };
  f.tick(); f.tick();
  assert.equal(f.requests.length, 2);
  f.dispose();
  assert.equal(f.requests[1].options.signal.aborted, true);
  resolve(new Response("new"));
  await settle();
  assert.equal(f.status.children.length, 0);
});

test("hidden tabs skip initial, interval and focus checks until visibility returns", async () => {
  const f = fixture({ visibility: "hidden", answers: ["old", "new"] });
  await settle();
  f.tick();
  f.windowNode.dispatchEvent(new Event("focus"));
  await settle();
  assert.equal(f.requests.length, 0);
  f.doc.visibilityState = "visible";
  f.doc.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(f.requests.length, 1);
  f.doc.visibilityState = "hidden";
  f.tick();
  f.windowNode.dispatchEvent(new Event("focus"));
  f.doc.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(f.requests.length, 1);
  f.doc.visibilityState = "visible";
  f.doc.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(f.status.children.length, 1);
  assert.equal(f.requests.length, 2);
  f.dispose();
});
