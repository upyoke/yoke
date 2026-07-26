// Read-only universe view. Hand-authored vanilla JS: no build step and no
// framework. Everything ships inside the yoke-core wheel.
//
// Mount contract: `mountUniverseApp(rootNode, options?)` renders into a
// host-owned node. The default options preserve `yoke ui`: same-origin
// cookie-authenticated calls to /api/functions/call and no outer slots.
// Another same-realm host may inject its own function client, opaque generic
// capabilities/actions, named slot nodes, and per-view sections without
// forking this app.
//
// Views are hash-routed as `#/<view>[/<segment>]?project=<id>[,<id>…]` so a
// shared link restores the view, its facet, and the scope. The left nav is
// data-driven (see NAV) — adding a route is one more array entry, with no
// per-view branching in the markup. The second segment means what the view
// declares: a tab (one facet of the view's concept, from the entry's `tabs`
// roster) or a drill-in (one row, with a breadcrumb back) — never both.
//
// Scope is per-screen: each view remembers its own scope and declares how it
// takes it (see SCOPE_*). A multi view reads the whole universe ("all", no
// query) or a set of projects; a single view configures exactly one. Live
// scoped views carry their own chip picker; stubs do not render a control
// that cannot act.
//
// Members and Billing sit in NAV as host-fed destinations in the one flat
// arc: the workbench routes them and draws their page head, but their body
// is the host's `sections` entry, and each nav entry shows exactly when its
// section is supplied. The workbench itself still has no notion of an
// account — the content stays host-owned.

import {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
import {
  attachMountRootClass,
  createUnmountHandle, detachMountedSlots, materializeSections,
  materializeSlots, validateMountRoot,
} from "./mount-options.js";
import {
  buildUniverseRoute,
  createScopePicker,
  createTabBar,
  NAV,
  navEntry,
  parseUniverseRoute,
  rememberedScopeParam,
  renderStubView,
  SCOPE_NONE,
  scopeForEntry,
  serializeScope,
  universeNavScope,
} from "./universe_navigation.js";
import {
  DETAIL_RENDERERS, TAB_RENDERERS, VIEW_RENDERERS,
} from "./universe_views.js";
import {
  callFunction,
  createBreadcrumb,
  createPageHead,
  createWorkbenchChrome,
  drillInProject,
  el,
  emptyUniversePanel,
} from "./universe_app_chrome.js";

export {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
export { buildUniverseRoute, parseUniverseRoute, universeNavScope };

const WORDMARK_ASSET_URL = new URL("./yoke-wordmark.svg", import.meta.url);

export function mountUniverseApp(rootNode, options = {}) {
  validateMountRoot(rootNode);
  const documentNode = rootNode.ownerDocument;
  const windowNode = documentNode && documentNode.defaultView;
  if (!documentNode || !windowNode) {
    throw new TypeError("mountUniverseApp root must belong to a window");
  }
  const client = options.client || createHttpFunctionClient();
  if (!client || typeof client.call !== "function") {
    throw new TypeError("mountUniverseApp client must expose call(request)");
  }
  const capabilities = options.capabilities || {};
  const slots = options.slots || {};
  // Slots and sections share one duplicate ledger: a node placed as both a
  // slot and a section is one Element asked to stand in two places.
  const hostContentNodes = new Set();
  const resolvedSlots = materializeSlots(slots, rootNode, hostContentNodes);
  const resolvedSections = materializeSections(
    options.sections || {}, rootNode, hostContentNodes,
  );
  const sectionNodes = Object.values(resolvedSections)
    .map((hostSection) => hostSection.content);
  const mountedSlotNodes = [];
  let mounted = true;
  let projects = [];
  const context = {
    client,
    document: documentNode,
    isMounted: () => mounted,
    navigate: (route) => { windowNode.location.hash = route; },
    // The roster the scope pickers already hold, so a view that only lists
    // projects costs no second call.
    projects: () => projects,
    // Host capability data, read by views that need an explicit deployment
    // mode or host-owned control surface. The Organization view interprets
    // portability capabilities; the topbar carries no capability controls.
    capabilities,
  };

  const {
    brand, header, main, navLinks, orgContext, shell,
  } = createWorkbenchChrome({
    documentNode,
    mountedSlotNodes,
    options,
    resolvedSections,
    resolvedSlots,
    slots,
  });

  const detachRootClass = attachMountRootClass(rootNode);
  rootNode.replaceChildren(header, shell);

  // The mark uses currentColor, so it must live in the DOM (an <img src>
  // would not inherit color); the brand container's ink flips in dark mode.
  Promise.resolve().then(() => globalThis.fetch(WORDMARK_ASSET_URL))
    .then((response) => response.text())
    .then((svg) => { if (mounted) brand.innerHTML = svg; })
    .catch(() => { if (mounted) brand.textContent = "Yoke"; });

  // The org read exists only to fill the app's own org naming, so a
  // suppressed org-context skips the call entirely.
  if (orgContext) {
    Promise.resolve().then(() => callFunction(client, "organizations.get", {}))
      .then((callResult) => {
        if (!mounted) return;
        const org = (callResult.envelope && callResult.envelope.result) || {};
        orgContext.textContent = org.name || "(unnamed org)";
      })
      .catch(() => { if (mounted) orgContext.textContent = ""; });
  }

  // Each visited scoped view remembers its own project.
  const scopeSelections = new Map();

  // A host section renders inside the view host, after whatever the view
  // renders for itself — one seam every view shares, so the host never
  // reaches into a renderer's own output. `scoped` marks the pages that drew
  // a picker: only there does a `beforeScope` section belong somewhere else,
  // and `beforeScopeSections` has already lifted it above that control. A
  // page with no picker has no control for it to sit above, so both
  // placements land here and no section can silently go unplaced.
  function appendViewSection(entry, viewHost, { scoped = false } = {}) {
    const hostSection = resolvedSections[entry.id];
    if (!hostSection) return;
    if (scoped && hostSection.placement === "beforeScope") return;
    viewHost.appendChild(hostSection.content);
  }

  // The host section the view's scope does not govern, placed above the scope
  // control so the picker never appears to filter facts it cannot touch. A
  // view whose section is `inView` contributes nothing here.
  function beforeScopeSections(entry) {
    const hostSection = resolvedSections[entry.id];
    return (hostSection && hostSection.placement === "beforeScope")
      ? [hostSection.content] : [];
  }

  function renderRoute() {
    // A section the previous route mounted leaves before the new route
    // renders, so the host's node reference never strands inside a
    // discarded subtree.
    detachMountedSlots(rootNode, sectionNodes);
    const route = parseUniverseRoute(windowNode.location.hash);
    const entry = navEntry(route.view);
    const scope = scopeForEntry(
      entry, route.project, projects, scopeSelections,
    );

    for (const navItem of NAV) {
      const link = navLinks.get(navItem.id);
      // A host-fed destination without its section built no link at all.
      if (!link) continue;
      // Each destination's link carries the scope that screen remembers for
      // itself — an "all" or never-visited multi view links with no query.
      link.href = buildUniverseRoute(
        navItem.id, rememberedScopeParam(navItem, projects, scopeSelections),
      );
      link.classList.toggle("active", navItem.id === entry.id);
    }

    if (entry.hostFed) {
      // The page head still belongs to the route; only the body is the
      // host's. A deep link whose host supplied nothing states honestly
      // that the screen is not here — this mount cannot render it.
      const viewHost = el(documentNode, "div", "view-host");
      main.replaceChildren(createPageHead(documentNode, entry), viewHost);
      // A host-fed view renders no body of its own and carries no picker, so
      // its section is the whole body at either placement.
      const hostSection = resolvedSections[entry.id];
      if (hostSection) viewHost.appendChild(hostSection.content);
      else renderStubView(context, viewHost);
      return;
    }

    if (entry.tabs) {
      // The segment is a tab facet: parse already resolved it to one of the
      // entry's declared tabs, so the strip and the body agree by construction.
      const tab = entry.tabs.find((item) => item.id === route.tab);
      const tabBar = createTabBar(
        documentNode, entry, tab.id, serializeScope(scope),
      );
      const pageHead = createPageHead(documentNode, entry);
      const tabRenderer = (TAB_RENDERERS[entry.id] || {})[tab.id];
      if (!tabRenderer) {
        // An unbuilt facet is honest the same way an unbuilt destination is,
        // and it carries no picker — a scope control over nothing filters
        // nothing. The facet's own what-it-will-be line renders inside the
        // stub: the page head names the view, not the tab.
        const stubHost = el(documentNode, "div", "view-host");
        main.replaceChildren(pageHead, tabBar, stubHost);
        renderStubView(context, stubHost, tab.summary);
        appendViewSection(entry, stubHost);
        return;
      }
      if (entry.scope === SCOPE_NONE) {
        const viewHost = el(documentNode, "div", "view-host");
        main.replaceChildren(pageHead, tabBar, viewHost);
        tabRenderer(context, viewHost, null);
        appendViewSection(entry, viewHost);
        return;
      }
      // Only a single-scope view needs a project to exist: an unfiltered
      // read over an empty universe is honest, an unscoped single view has
      // nothing to configure.
      if (scope === null) {
        const emptyHost = el(documentNode, "div", "view-host");
        emptyHost.appendChild(emptyUniversePanel(documentNode));
        appendViewSection(entry, emptyHost);
        main.replaceChildren(pageHead, tabBar, emptyHost);
        return;
      }
      // A built tab carries its own picker before the facet strip. Project
      // scope governs every facet, so the scope is chosen before the user
      // selects which facet of that scoped data to inspect.
      const viewHost = el(documentNode, "div", "view-host");
      main.replaceChildren(
        pageHead,
        ...beforeScopeSections(entry),
        createScopePicker({
          documentNode, entry, scope, projects, renderRoute,
          scopeSelections, segment: tab.id, windowNode,
        }),
        tabBar,
        viewHost,
      );
      tabRenderer(context, viewHost, scope);
      appendViewSection(entry, viewHost, { scoped: true });
      return;
    }

    const detailRenderer = route.detail ? DETAIL_RENDERERS[entry.id] : null;
    const renderer = VIEW_RENDERERS[entry.id];
    if (!renderer) {
      const stubHost = el(documentNode, "div", "view-host");
      main.replaceChildren(createPageHead(documentNode, entry), stubHost);
      renderStubView(context, stubHost);
      appendViewSection(entry, stubHost);
      return;
    }
    if (entry.scope === SCOPE_NONE) {
      const viewHost = el(documentNode, "div", "view-host");
      main.replaceChildren(createPageHead(documentNode, entry), viewHost);
      renderer(context, viewHost, null);
      appendViewSection(entry, viewHost);
      return;
    }
    // Only a single-scope view needs a project to exist (see the tab path).
    if (scope === null) {
      const emptyHost = el(documentNode, "div", "view-host");
      emptyHost.appendChild(emptyUniversePanel(documentNode));
      appendViewSection(entry, emptyHost);
      main.replaceChildren(createPageHead(documentNode, entry), emptyHost);
      return;
    }
    const detailProject = detailRenderer
      ? drillInProject(scope, projects) : null;
    if (detailRenderer && detailProject !== null) {
      // A drill-in swaps the view's picker for a breadcrumb, and the
      // breadcrumb is a drill-in's whole head: re-scoping a single row to
      // another project is nonsense, and the way out is back. The view's
      // host section stays out too — it belongs to the view, not to one row.
      const detailHost = el(documentNode, "div", "view-host");
      main.replaceChildren(
        createBreadcrumb(
          documentNode, entry, serializeScope(scope), route.detail,
        ),
        detailHost,
      );
      detailRenderer(context, detailHost, detailProject, route.detail);
      return;
    }
    // The picker is the view's own chrome, so it sits in the content column
    // above a host the view owns outright and re-renders into at will.
    const viewHost = el(documentNode, "div", "view-host");
    main.replaceChildren(
      createPageHead(documentNode, entry),
      ...beforeScopeSections(entry),
      createScopePicker({
        documentNode, entry, scope, projects, renderRoute, scopeSelections,
        windowNode,
      }),
      viewHost,
    );
    renderer(context, viewHost, scope);
    appendViewSection(entry, viewHost, { scoped: true });
  }

  windowNode.addEventListener("hashchange", renderRoute);

  Promise.resolve().then(() => callFunction(
    client, "projects.list", { fields: ["id", "slug", "name"] },
  ))
    .then((callResult) => {
      const result = (callResult.envelope && callResult.envelope.result) || {};
      projects = result.rows || [];
    })
    // A roster that fails to load leaves the universe empty. The catch stays
    // on the fetch alone: folding the first render into it would report any
    // view's render error as "no projects yet".
    .catch(() => { projects = []; })
    .then(() => { if (mounted) renderRoute(); });

  return createUnmountHandle(UNIVERSE_APP_CONTRACT_VERSION, () => {
    mounted = false;
    windowNode.removeEventListener("hashchange", renderRoute);
    detachMountedSlots(rootNode, [...mountedSlotNodes, ...sectionNodes]);
    rootNode.replaceChildren();
    detachRootClass();
  });
}
