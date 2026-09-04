import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  SEARCH_DEBOUNCE_MS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shell_controls.js";
import {
  FakeDocument, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";

// Header search debounces keystrokes, so its results land on a timer rather
// than a microtask; settle() alone does not reach them.
async function settleSearch() {
  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 20));
  await settle();
}

// A session older than the roster's recency window: reachable only by the
// read that names its id.
const ARCHIVED_SESSION_ID = "claude-code-20260403T152218Z-56305";

function keyEvent(key, extras = {}) {
  const event = new Event("keydown");
  Object.defineProperties(event, {
    key: { value: key },
    metaKey: { value: Boolean(extras.metaKey) },
    ctrlKey: { value: Boolean(extras.ctrlKey) },
  });
  return event;
}

test("shared shell search, footer, identity, and scroll contract are live", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const searchRequests = [];
  const sessionIdReads = [];
  const client = {
    async call(request) {
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        } } };
      }
      if (request.function === "items.search.run") {
        searchRequests.push(request.payload);
        // The shape items.search.run really returns: `id` renders the public
        // ref and `internal_id` carries the numeric key.
        return { status: 200, envelope: { success: true, result: {
          // Nothing in the backlog is named by a session id.
          matches: request.payload.keywords === ARCHIVED_SESSION_ID ? [] : [{
            id: "YOK-2228", internal_id: 2262, title: "Build shell",
            project_id: 1, project: "yoke", status: "implementing",
          }],
        } } };
      }
      if (request.function === "sessions.list") {
        if (request.payload?.session_id) {
          sessionIdReads.push(request.payload.session_id);
          return { status: 200, envelope: { success: true, result: {
            rows: request.payload.session_id === ARCHIVED_SESSION_ID
              ? [{
                session_id: ARCHIVED_SESSION_ID, project_id: 1,
                project: "yoke", executor: "codex",
              }]
              : [],
          } } };
        }
        return { status: 200, envelope: { success: true, result: {
          rows: [{
            session_id: "session-shell", project_id: 1, project: "yoke",
            current_item: "YOK-21", current_item_title: "Build shell",
            executor: "codex",
          }],
        } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, {
    client,
    currentActor: { id: 2, kind: "human", label: "ben" },
    environmentLabel: "stage · yoke",
    versionLabel: "v9.4.1",
    runtimeIdentity: {
      version: "v9.4.1",
      installKind: "packaged_wheel",
      build: "abc123def456",
      environmentLabel: "stage · yoke",
      portabilityMode: "hosted",
    },
  });
  await settle();

  assert.equal(byClass(root, "header-search-input").length, 1);
  assert.equal(byClass(root, "actor-avatar")[0].textContent, "b");
  assert.equal(byClass(root, "actor-kind")[0].textContent, "actor 2");
  assert.equal(byClass(root, "app-footer-environment")[0].textContent,
    "stage · yoke");
  assert.equal(byClass(root, "app-footer-version")[0].textContent, "v9.4.1");
  assert.match(byClass(root, "app-footer-link")[0].href,
    /github\.com\/upyoke\/yoke\/tree\/main\/docs/);

  const versionControl = byClass(root, "app-footer-version")[0];
  assert.equal(versionControl.tagName.toLowerCase(), "button");
  assert.equal(byClass(root, "runtime-identity-help")[0].hidden, true);
  versionControl.dispatchEvent(new Event("click"));
  const identityPanel = byClass(root, "runtime-identity-help")[0];
  assert.equal(identityPanel.hidden, false);
  const identityValues = byClass(root, "runtime-identity-help-value")
    .map((node) => node.textContent);
  assert.deepEqual(identityValues, [
    "v9.4.1", "packaged_wheel", "abc123def456", "stage · yoke", "hosted",
  ]);

  const input = byClass(root, "header-search-input")[0];
  input.value = "shell";
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  const links = byClass(root, "header-search-result");
  // The item leads, and it is offered at all only because the row is read
  // the way items.search.run writes it.
  assert.equal(links.length, 2);
  assert.equal(links[0].href, "#/items/2228?project=1");
  assert.equal(byClass(root, "header-search-kind")[0].textContent, "Item");
  assert.equal(byClass(root, "header-search-label")[0].textContent,
    "Build shell");
  assert.equal(byClass(root, "header-search-meta")[0].textContent,
    "YOK-2228 · yoke · implementing");
  // A session result opens that session's own page rather than the roster it
  // would have to be found in a second time.
  assert.equal(links[1].href, "#/sessions/session-shell?project=1");
  // Items are matched by the server, so the typed query travels with the
  // request — the browser never filters a prefetched roster it could outgrow.
  assert.deepEqual(searchRequests.at(-1), { keywords: "shell", limit: 8 });

  // Every shape an operator uses to name one item reaches the item result:
  // the bare number, the full ref, and the ref in either case.
  for (const keywords of ["2228", "YOK-2228", "yok-2228", "Build shell"]) {
    input.value = keywords;
    input.dispatchEvent(new Event("input"));
    await settleSearch();
    assert.deepEqual(searchRequests.at(-1), { keywords, limit: 8 });
    const matched = byClass(root, "header-search-result");
    assert.equal(matched[0].href, "#/items/2228?project=1");
  }

  // A session past the roster's recency window is read by its own id, so a
  // full session id finds it however old it is.
  input.value = ARCHIVED_SESSION_ID;
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  assert.ok(sessionIdReads.includes(ARCHIVED_SESSION_ID));
  const archived = byClass(root, "header-search-result");
  assert.equal(archived.length, 1);
  assert.equal(archived[0].href,
    `#/sessions/${ARCHIVED_SESSION_ID}?project=1`);

  // A query the client could not have matched locally still resolves: the
  // item's own text says nothing about the number the operator typed.
  input.value = "YOK-21";
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  assert.deepEqual(searchRequests.at(-1), { keywords: "YOK-21", limit: 8 });
  assert.equal(byClass(root, "header-search-result")[0].href,
    "#/items/2228?project=1");

  // A burst of keystrokes settles into one request rather than one each.
  const beforeBurst = searchRequests.length;
  for (const value of ["hea", "head", "heade", "header"]) {
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
  await settleSearch();
  assert.equal(searchRequests.length - beforeBurst, 1);
  assert.equal(searchRequests.at(-1).keywords, "header");

  input.value = "shell";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  input.dispatchEvent(keyEvent("ArrowDown"));
  input.dispatchEvent(keyEvent("Enter"));
  assert.equal(documentNode.defaultView.location.hash,
    "#/items/2228?project=1");
  const main = byClass(root, "content")[0];
  main.scrollTop = 600;
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  assert.equal(main.scrollTop, 0);

  const keyboard = byClass(root, "keyboard-help-toggle")[0];
  keyboard.dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "keyboard-help")[0].hidden, false);
  documentNode.defaultView.dispatchEvent(keyEvent("Escape"));
  assert.equal(byClass(root, "keyboard-help")[0].hidden, true);
  mounted.unmount();
  assert.equal(documentNode.defaultView.listenerCounts.get("keydown"), 0);
});

test("compact route changes reveal the active destination without moving the desktop rail", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  let navDirection = "column";
  const scrollCalls = [];
  const createElement = documentNode.createElement.bind(documentNode);
  documentNode.createElement = (tagName) => {
    const node = createElement(tagName);
    node.scrollIntoView = (options) => {
      scrollCalls.push({ node, options });
    };
    return node;
  };
  documentNode.defaultView.getComputedStyle = (node) => ({
    flexDirection: node.classList.contains("sidenav")
      ? navDirection : "column",
  });
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [{ id: 1, slug: "yoke", name: "Yoke" }],
        } } };
      }
      if (request.function === "items.overview.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [],
        } } };
      }
      if (request.function === "sessions.list") {
        return { status: 200, envelope: { success: true, result: {
          rows: [],
        } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.equal(scrollCalls.length, 0);
  navDirection = "row";
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();

  assert.equal(
    scrollCalls.at(-1).node.children[1].textContent,
    "Sessions",
  );
  assert.deepEqual(
    scrollCalls.at(-1).options,
    { block: "nearest", inline: "nearest" },
  );
  const compactScrollCount = scrollCalls.length;
  navDirection = "column";
  documentNode.defaultView.location.hash = "#/items?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(scrollCalls.length, compactScrollCount);

  mounted.unmount();
});

test("compact chrome opens the navigation drawer and shared search overlay", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.body = documentNode.createElement("body");
  documentNode.defaultView.innerWidth = 900;
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{
          id: 1, slug: "yoke", name: "Yoke", public_item_prefix: "YOK",
        }] } } };
      }
      if (request.function === "items.overview.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const shell = byClass(root, "shell")[0];
  const navToggle = byClass(root, "navigation-toggle")[0];
  const scrim = byClass(root, "navigation-scrim")[0];
  navToggle.dispatchEvent(new Event("click"));
  assert.equal(shell.classList.contains("side-open"), true);
  assert.equal(documentNode.body.classList.contains("side-open"), true);
  assert.equal(navToggle.getAttribute("aria-expanded"), "true");
  assert.equal(scrim.hidden, false);
  scrim.dispatchEvent(new Event("click"));
  assert.equal(shell.classList.contains("side-open"), false);

  const searchButton = byClass(root, "header-search-button")[0];
  const overlay = byClass(root, "header-search-overlay")[0];
  searchButton.dispatchEvent(new Event("click"));
  assert.equal(overlay.hidden, false);
  assert.equal(documentNode.activeElement, byClass(root, "header-search-input")[0]);
  byClass(root, "header-search-close")[0].dispatchEvent(new Event("click"));
  assert.equal(overlay.hidden, true);
  mounted.unmount();
  assert.equal(documentNode.body.classList.contains("side-open"), false);
});
