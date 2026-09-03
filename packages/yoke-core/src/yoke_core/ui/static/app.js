// Read-only, hand-authored universe app. `mountUniverseApp(rootNode, options?)`
// accepts same-realm clients, host slots, and sections without forking the UI.
// Hash routes preserve each view's declared scope and drill-in. NAV owns
// the flat destination arc; host-fed Members and Billing contribute only their
// body while the workbench retains routing and page chrome.

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
  DETAIL_RENDERERS, VIEW_RENDERERS,
} from "./universe_views.js";
import {
  callFunction,
  configurePageHead,
  createBreadcrumb,
  createPageHead,
  createWorkbenchChrome,
  drillInProject,
  el,
  emptyUniversePanel,
} from "./universe_app_chrome.js";
import {
  createHeldScopeController,
  createHostSectionPlacement,
  loadOrganizationName,
  loadWordmark,
} from "./universe_app_shell_support.js";
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
  // Slots and sections share one duplicate-node ledger.
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
    brand, disposeChrome, header, main, navLinks, orgContext, shell,
  } = createWorkbenchChrome({
    client,
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
  loadWordmark(brand, WORDMARK_ASSET_URL, () => mounted);

  // The org read exists only to fill the app's own org naming, so a
  // suppressed org-context skips the call entirely.
  loadOrganizationName(client, orgContext, () => mounted);

  // Each visited scoped view remembers its own project.
  const scopeSelections = new Map();

  // A host section renders inside the view host, after whatever the view
  // renders for itself — one seam every view shares, so the host never
  // reaches into a renderer's own output. `scoped` marks the pages that drew
  // a picker: only there does a `beforeScope` section belong somewhere else,
  // and `beforeScopeSections` has already lifted it above that control. A
  // page with no picker has no control for it to sit above, so both
  // placements land here and no section can silently go unplaced.
  const {
    append: appendViewSection,
    beforeScope: beforeScopeSections,
  } = createHostSectionPlacement(resolvedSections);

  const heldScope = createHeldScopeController({
    windowNode, scopeSelections, renderRoute, projectsRef: () => projects,
    navEntry, scopeForEntry, serializeScope, parseUniverseRoute,
    navLinks, nav: NAV, buildUniverseRoute, rememberedScopeParam,
  });

  function renderRoute() {
    // The nav keeps its own position, but every destination begins at the
    // top of its independent content scroller.
    main.scrollTop = 0;
    // A section the previous route mounted leaves before the new route
    // renders, so the host's node reference never strands inside a
    // discarded subtree.
    detachMountedSlots(rootNode, sectionNodes);
    heldScope.reset(); // a full render drops any held scoped view
    const route = parseUniverseRoute(windowNode.location.hash);
    const entry = navEntry(route.view);
    const scope = scopeForEntry(
      entry, route.project, projects, scopeSelections,
    );
    const breadcrumbNavigation = (breadcrumb) => ({
      setDetailLabel(label) {
        if (!mounted || main.children[0] !== breadcrumb) return;
        breadcrumb.children[breadcrumb.children.length - 1].textContent =
          String(label);
      },
    });

    heldScope.refreshNavHrefs(entry.id);

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
      renderer(context, viewHost, null, route.detail);
      appendViewSection(entry, viewHost);
      return;
    }
    // Only a single-scope view needs a project to exist: an unfiltered read
    // over an empty universe is honest, an unscoped single view has nothing
    // to configure.
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
      // A drill-in swaps the view's picker for a breadcrumb. Its renderer
      // owns the detail page head below that trail; re-scoping one row to
      // another project is nonsense. The view's host section stays out too
      // — it belongs to the view, not to one row.
      const detailHost = el(documentNode, "div", "view-host");
      const breadcrumb = createBreadcrumb(
        documentNode, entry, serializeScope(scope), route.detail,
      );
      main.replaceChildren(breadcrumb, detailHost);
      detailRenderer(
        context,
        detailHost,
        detailProject,
        route.detail,
        breadcrumbNavigation(breadcrumb),
      );
      return;
    }
    // The picker is the view's own chrome; above it sits a view-owned host
    // (the Overview pins its activation stack there), and the view host below.
    const viewHost = el(documentNode, "div", "view-host"), aboveScope = el(documentNode, "div", "view-above-scope");
    const pageHead = createPageHead(documentNode, entry);
    const picker = createScopePicker({
      documentNode, entry, scope, projects, renderRoute, scopeSelections,
      windowNode, onScopeChange: heldScope.applyScopeInPlace,
    });
    main.replaceChildren(
      pageHead, ...beforeScopeSections(entry), aboveScope, picker, viewHost,
    );
    const handle = renderer(context, viewHost, scope, { aboveScope,
      setPageHead(options) {
        if (!mounted || main.children[0] !== pageHead) return;
        configurePageHead(documentNode, pageHead, options);
      },
    });
    appendViewSection(entry, viewHost, { scoped: true });
    heldScope.register(entry.id, scope, picker, handle);
  }

  windowNode.addEventListener("hashchange", heldScope.onHashChange);

  Promise.resolve().then(() => callFunction(
    client, "projects.list", { fields: ["id", "slug", "name", "emoji"] },
  )).then((callResult) => {
    projects = (callResult.envelope && callResult.envelope.result)?.rows || [];
  })
    // A roster that fails to load leaves the universe empty. The catch stays
    // on the fetch alone: folding the first render into it would report any
    // view's render error as "no projects yet".
    .catch(() => { projects = []; })
    .then(() => { if (mounted) renderRoute(); });

  return createUnmountHandle(UNIVERSE_APP_CONTRACT_VERSION, () => {
    mounted = false;
    windowNode.removeEventListener("hashchange", heldScope.onHashChange);
    disposeChrome();
    detachMountedSlots(rootNode, [...mountedSlotNodes, ...sectionNodes]);
    rootNode.replaceChildren();
    detachRootClass();
  });
}
