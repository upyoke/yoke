// Selecting every project is the All scope, not a second state beside it.
// Two representations of one scope let the stored value, the route and the
// chip row disagree: the All chip stays unlit, the chip row turns
// subtractive (clicking a project turns it off) where every other
// "everything" state narrows to that project, and the selection an operator
// aims at is unreachable in one click.
import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  itemsCalls, scopeChips, threeProjectClient, twoProjectClient,
} from "./universe_ui_read_views_test_support.mjs";

function preferenceClient(initialViews = {}, universeClient = twoProjectClient) {
  const base = universeClient();
  const state = { views: { ...initialViews } };
  return {
    requests: base.requests,
    state,
    async call(request) {
      if (request.function === "ui_preferences.screen_selection.list") {
        base.requests.push(request);
        return { status: 200, envelope: { success: true, result: { views: state.views } } };
      }
      if (request.function === "ui_preferences.screen_selection.set") {
        base.requests.push(request);
        state.views = {
          ...state.views,
          [request.payload.view_id]: {
            selection: request.payload.selection, focus: request.payload.focus,
          },
        };
        return { status: 200, envelope: { success: true, result: {} } };
      }
      return base.call(request);
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = hash;
  windowNode.history = { replaceState(_state, _title, route) {
    windowNode.location.hash = route;
  } };
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  t.after(() => mounted.unmount());
  await settle();
  return {
    root,
    windowNode,
    on: () => scopeChips(root)
      .filter((chip) => chip.classList.contains("on"))
      .map((chip) => chip.textContent),
    async click(label) {
      scopeChips(root).find((chip) => chip.textContent === label)
        .dispatchEvent(new Event("click"));
      await settle();
    },
  };
}

test("adding the last missing project is All, and the next click narrows from it", async (t) => {
  const client = preferenceClient({}, threeProjectClient);
  const app = await mountAt(t, "#/items", client);

  await app.click("ALP");
  await app.click("BET");
  assert.deepEqual(app.on(), ["ALP", "BET"]);
  assert.deepEqual(client.state.views.items.selection, ["1", "2"]);

  // The chip that completes the roster does not make a third selected chip
  // beside an unlit All — it IS All.
  await app.click("GAM");
  assert.deepEqual(app.on(), ["All"]);
  assert.equal(client.state.views.items.selection, "all");
  assert.equal(app.windowNode.location.hash, "#/items?project=all");
  assert.equal(itemsCalls(client).at(-1).payload.projects, undefined);

  // And because it is All, the next click narrows to that one project
  // instead of turning it off and leaving the other two selected.
  await app.click("ALP");
  assert.deepEqual(app.on(), ["ALP"]);
  assert.deepEqual(client.state.views.items.selection, ["1"]);
});

test("a stored full-roster member list resolves to All on the first render", async (t) => {
  // What prod already holds for screens that reached the full set before it
  // was canonical. The restore path must not carry that second form forward.
  const client = preferenceClient(
    { items: { selection: ["1", "2", "3"], focus: null } }, threeProjectClient,
  );
  const app = await mountAt(t, "#/items", client);
  assert.deepEqual(app.on(), ["All"]);
  assert.equal(app.windowNode.location.hash, "#/items?project=all");
  // Written back in the canonical form, so the next mount reads one scope
  // in one shape rather than healing it again.
  assert.equal(client.state.views.items.selection, "all");
});

test("a route naming every project resolves to All rather than pinning the set", async (t) => {
  const client = preferenceClient({}, threeProjectClient);
  const app = await mountAt(t, "#/items?project=1,2,3", client);
  assert.deepEqual(app.on(), ["All"]);
  assert.equal(app.windowNode.location.hash, "#/items?project=all");
  // Nothing to write: the route named the scope this screen already
  // defaults to, so resolving it is not a change.
  assert.equal(client.state.views.items, undefined);
});

test("a screen's own links carry the canonical form of what it remembers", async (t) => {
  // Cross-screen drill-ins (Frontier's see-more, a work card's fallback
  // href) encode the current scope into the target's route, so a full-roster
  // scope must reach them as All — otherwise one screen writes the
  // non-canonical set into another screen's remembered selection.
  const client = preferenceClient(
    {
      items: { selection: ["1", "2", "3"], focus: null },
      frontier: { selection: ["1", "2", "3"], focus: null },
    },
    threeProjectClient,
  );
  const app = await mountAt(t, "#/strategy", client);
  const scoped = byClass(app.root, "nav-link")
    .map((link) => link.href)
    .filter((href) => href && (href.startsWith("#/items") || href.startsWith("#/frontier")));
  assert.ok(scoped.length >= 2, `expected scoped nav links, got ${scoped}`);
  for (const href of scoped) {
    assert.match(href, /project=all/, `${href} should carry the canonical All scope`);
  }
});
