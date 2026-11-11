import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp, buildUniverseRoute, parseUniverseRoute, UNIVERSE_APP_CONTRACT_VERSION } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { NAV, MOVED_VIEWS } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_destinations.js";
import { routeHref, routeDocumentTitle } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { locationResolves } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_location_preference.js";
import { FakeDocument, allNodes, byClass, injectedClient, response, settle } from "./universe_ui_dom_test_support.mjs";

import { NAV_ICONS } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_nav_icons.js";

const basePath = "/orgs/sample";
function group(content) {
  return [{ id: "host-tools", label: "Host tools", pages: [
    { id: "reports", label: "Reports", content },
    { id: "exports", label: "Exports", content: () => null },
  ] }];
}
async function mount(t, href, navigation, client = injectedClient("host"), onWindow = () => {}) {
  const original = globalThis.fetch;
  globalThis.fetch = () => response(200, {});
  t.after(() => { globalThis.fetch = original; });
  const document = new FakeDocument(), window = document.defaultView;
  window.fetch = () => response(503, {});
  window.location.href = href;
  onWindow(window);
  const root = document.createElement("div");
  const app = mountUniverseApp(root, { basePath, navigation, client, universeId: "sample" });
  t.after(() => app.unmount());
  await settle();
  return { root, document, window, app };
}

test("host groups append in order, deep links and reload render unscoped content", async (t) => {
  const contexts = [];
  const navigation = group((context) => {
    contexts.push(context);
    return null;
  });
  navigation.push({ id: "empty", label: "Empty host group", pages: [] });
  for (let reload = 0; reload < 2; reload++) {
    const mounted = await mount(t, `${basePath}/reports/annual%20report?project=1`, navigation);
    const headings = byClass(mounted.root, "nav-group").map(node => node.textContent);
    assert.equal(headings.at(-1), "Host tools");
    assert.ok(headings.indexOf("Diagnostics") < headings.indexOf("Host tools"));
    assert.ok(!headings.includes("Empty host group"));
    const links = byClass(mounted.root, "nav-link");
    assert.deepEqual(links.slice(-2).map(link => link.children[1].textContent), ["Reports", "Exports"]);
    const active = links.find(link => link.classList.contains("active"));
    assert.equal(active.children[1].textContent, "Reports");
    assert.equal(active.getAttribute("aria-current"), "page");
    assert.equal(active.href, `${basePath}/reports`);
    assert.equal(byClass(mounted.root, "title")[0].textContent, "Reports");
    assert.equal(mounted.document.title, "annual report · Reports · Yoke");
    assert.equal(byClass(mounted.root, "scope-bar").length, 0);
    assert.equal(mounted.window.location.href, `${basePath}/reports/annual%20report?project=1`);
    assert.equal(contexts.at(-1).universeId, "sample");
    assert.equal(contexts.at(-1).scope, null);
    assert.equal(contexts.at(-1).projectSelection, "all");
    assert.equal(contexts.at(-1).detail, "annual report");
    mounted.app.unmount();
    assert.ok(contexts.at(-1).signal.aborted);
  }
  assert.equal(UNIVERSE_APP_CONTRACT_VERSION, 11);
});

test("host route resolution preserves opaque queries and fragments on open and reload", async (t) => {
  const href = `${basePath}/reports/annual%20report?status=new&status=read&project=1&selection=all&opaque=a%2Bb#details`;
  let reloadedHref = href;
  for (let reload = 0; reload < 2; reload++) {
    let contentHref, hostWindow;
    const mounted = await mount(t, reloadedHref, group(() => {
      contentHref = hostWindow.location.href;
      return null;
    }), undefined, window => { hostWindow = window; });
    assert.equal(mounted.window.location.href, href);
    assert.equal(contentHref, href);
    reloadedHref = mounted.window.location.href;
    mounted.app.unmount();
  }
});

test("built-in route resolution still canonicalizes project selection", async (t) => {
  const mounted = await mount(t, `${basePath}/items?status=new&project=all#details`, group(() => null));
  assert.equal(mounted.window.location.href, `${basePath}/items?status=new&project=all`);
});

test("host pages own fragments that resemble legacy workbench bookmarks", async (t) => {
  const href = `${basePath}/reports?status=new#/exports?host=owned`;
  const mounted = await mount(t, href, group(() => null));
  assert.equal(mounted.window.location.href, href);
  assert.equal(byClass(mounted.root, "title")[0].textContent, "Reports");
});

test("host content anchors navigate within the app, aborting outgoing factories", async (t) => {
  const contexts = [];
  const document = new FakeDocument();
  const link = document.createElement("a");
  link.setAttribute("href", `${basePath}/reports/next`);
  link.closest = () => link;
  link.hasAttribute = name => link.attributes.has(name);
  const navigation = group(context => { contexts.push(context); return link; });
  const mounted = await mount(t, `${basePath}/reports`, navigation);
  assert.ok(allNodes(mounted.root).includes(link));
  const click = new Event("click", { cancelable: true });
  Object.defineProperty(click, "target", { value: link });
  mounted.root.dispatchEvent(click);
  await settle();
  assert.ok(click.defaultPrevented);
  assert.equal(mounted.window.location.href, `${basePath}/reports/next`);
  assert.ok(contexts[0].signal.aborted);
  assert.equal(contexts.at(-1).detail, "next");
  mounted.window.history.back();
  await settle();
  assert.equal(contexts.at(-1).detail, null);
  mounted.window.location.href = `${basePath}/exports`;
  mounted.window.dispatchEvent(new Event("popstate"));
  await settle();
  assert.ok(contexts.at(-1).signal.aborted);
  assert.equal(link.parentNode, null);
  assert.equal(byClass(mounted.root, "title")[0].textContent, "Exports");
});

test("page ids reject built-in and moved ids, invalid slugs and duplicates", () => {
  const document = new FakeDocument(), root = document.createElement("div");
  for (const id of [...NAV.map(entry => entry.id), ...Object.keys(MOVED_VIEWS)]) {
    const navigation = [{ id: "tools", label: "Tools", pages: [{ id, label: "Page", content: () => null }] }];
    assert.throws(() => mountUniverseApp(root, { navigation }), new RegExp(`host_page_id_reserved: ${id}`));
  }
  for (const id of ["UPPER", "has/slash", "", "a--b"]) {
    const navigation = group(() => null);
    navigation[0].pages[0].id = id;
    assert.throws(() => mountUniverseApp(root, { navigation }), /host_page_id_invalid/);
  }
  const navigation = group(() => null);
  navigation.push({ id: "other", label: "Other", pages: [navigation[0].pages[0]] });
  assert.throws(() => mountUniverseApp(root, { navigation }), /host_page_id_invalid: reports/);
});

test("helper routes resolve only this mount's pages and preserve unknown-path fallback", async () => {
  const navigation = group(() => null);
  const href = buildUniverseRoute("reports", "1", "annual report", null, basePath, navigation);
  assert.equal(href, `${basePath}/reports/annual%20report`);
  const route = parseUniverseRoute(href, basePath, navigation);
  assert.equal(route.view, "reports");
  assert.equal(route.detail, "annual report");
  assert.equal(route.project, null);
  assert.equal(routeHref(href, basePath, navigation), href);
  assert.equal(routeDocumentTitle(route, navigation), "annual report · Reports · Yoke");
  assert.equal(parseUniverseRoute(href, basePath).view, "strategy");
  assert.equal(routeHref(href, basePath), null);
  assert.deepEqual(parseUniverseRoute(`${basePath}/missing/detail`, basePath, navigation), parseUniverseRoute(`${basePath}/missing/detail`, basePath));
  assert.ok(await locationResolves({}, "/reports/annual", [], {}, "", navigation));
  assert.equal(await locationResolves({}, "/reports/annual", []), false);
  assert.equal(await locationResolves({}, "/reports/a/extra", [], {}, "", navigation), false);
});

test("bare mount restores a saved host detail, and absence keeps built-in navigation", async (t) => {
  const client = injectedClient("host"), call = client.call.bind(client);
  client.call = request => request.function === "ui_preferences.screen_selection.list"
    ? Promise.resolve({ status: 200, envelope: { success: true, result: { views: {}, last_location: "/reports/saved" } } })
    : call(request);
  const mounted = await mount(t, basePath, group(() => null), client);
  assert.equal(mounted.window.location.href, `${basePath}/reports/saved`);
  assert.equal(mounted.document.title, "saved · Reports · Yoke");
  mounted.app.unmount();
  const plain = await mount(t, `${basePath}/reports`, undefined);
  assert.equal(byClass(plain.root, "title")[0].textContent, "Strategy");
  assert.ok(!byClass(plain.root, "nav-group").some(node => node.textContent === "Host tools"));
});

test("factory failures show a diagnosis and cancel the signal", async (t) => {
  let signal;
  const mounted = await mount(t, `${basePath}/reports`, group(context => {
    signal = context.signal;
    throw new Error("host unavailable");
  }));
  assert.ok(signal.aborted);
  assert.match(byClass(mounted.root, "error-banner")[0].textContent, /host_page_render_failed: host unavailable.*reload/);
});


test("host page icons use existing keys and leave omitted or unknown slots blank", async (t) => {
  const navigation = group(() => null);
  navigation[0].pages[0].icon = "items";
  navigation[0].pages[1].icon = "unknown-icon";
  navigation[0].pages.push({ id: "archive", label: "Archive", content: () => null });
  navigation[0].pages.push({ id: "inherited", label: "Inherited", icon: "constructor", content: () => null });
  const mounted = await mount(t, `${basePath}/reports`, navigation);
  const links = byClass(mounted.root, "nav-link");
  assert.deepEqual(links.slice(-4).map(link => link.children[0].innerHTML), [NAV_ICONS.items, "", "", ""]);
  const strategy = links.find(link => link.children[1].textContent === "Strategy");
  assert.equal(strategy.children[0].innerHTML, NAV_ICONS.strategy);
});

test("host pages select the leads icon by key or through the id fallback", async (t) => {
  const navigation = group(() => null);
  navigation[0].pages[0].icon = "leads";
  navigation[0].pages.push({ id: "leads", label: "Leads", content: () => null });
  const mounted = await mount(t, `${basePath}/reports`, navigation);
  const links = byClass(mounted.root, "nav-link");
  assert.match(NAV_ICONS.leads, /stroke-width="1.75"/);
  assert.deepEqual(links.slice(-3).map(link => link.children[0].innerHTML), [NAV_ICONS.leads, "", NAV_ICONS.leads]);
});

test("collapsible host groups start closed and remember mouse and keyboard toggles on reload", async (t) => {
  const navigation = group(() => null);
  navigation[0].collapsible = true;
  const groups = {}, writes = [];
  const client = injectedClient("host"), call = client.call.bind(client);
  client.call = request => {
    if (request.function === "ui_preferences.nav_group.list") {
      return Promise.resolve({ status: 200, envelope: { success: true, result: { groups: { ...groups } } } });
    }
    if (request.function === "ui_preferences.nav_group.set") {
      writes.push(request.payload);
      groups[request.payload.group_id] = request.payload.open;
      return Promise.resolve({ status: 200, envelope: { success: true, result: {} } });
    }
    return call(request);
  };
  function disclosure(root) {
    const heading = byClass(root, "nav-group").find(node => node.textContent === "Host tools");
    const items = byClass(root, "nav-group-items").find(node => node.id === heading.getAttribute("aria-controls"));
    assert.equal(heading.getAttribute("role"), "button");
    assert.equal(heading.tabIndex, 0);
    return { heading, items };
  }
  const first = await mount(t, `${basePath}/reports`, navigation, client);
  let { heading, items } = disclosure(first.root);
  assert.equal(heading.getAttribute("aria-expanded"), "false");
  assert.equal(items.hidden, true);
  heading.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(items.hidden, false);
  assert.deepEqual(writes.at(-1), { group_id: "host-tools", open: true });
  first.app.unmount();

  const second = await mount(t, `${basePath}/reports`, navigation, client);
  ({ heading, items } = disclosure(second.root));
  assert.equal(heading.getAttribute("aria-expanded"), "true");
  assert.equal(items.hidden, false);
  for (const key of [" ", "Enter", "Enter"]) {
    const event = new Event("keydown", { cancelable: true });
    Object.defineProperty(event, "key", { value: key });
    heading.dispatchEvent(event);
    assert.ok(event.defaultPrevented);
    await settle();
  }
  assert.equal(items.hidden, true);
  assert.deepEqual(writes.at(-1), { group_id: "host-tools", open: false });
  second.app.unmount();
  const third = await mount(t, `${basePath}/reports`, navigation, client);
  assert.equal(disclosure(third.root).items.hidden, true);
});
