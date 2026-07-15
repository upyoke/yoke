// Read-only universe view. Hand-authored vanilla JS: no build step and no
// framework. Everything ships inside the yoke-core wheel.
//
// Mount contract: `mountUniverseApp(rootNode, options?)` renders into a
// host-owned node. The default options preserve `yoke ui`: same-origin
// cookie-authenticated calls to /api/functions/call and no outer slots.
// Another same-realm host may inject its own function client, opaque generic
// capabilities/actions, and named slot nodes without forking this app.
//
// Views are hash-routed as `#/<view>?project=<id>` so a shared link restores
// both the view and the scope. The left nav is data-driven (see NAV) — adding
// a route is one more array entry, with no per-view branching in the markup.
//
// Scope is per-screen: each view remembers its own project and declares how it
// takes scope (see SCOPE_*). Live scoped views carry their own picker; stubs do
// not render a control that cannot act.
//
// Members and Billing are deliberately absent from NAV. They are hosted
// chrome the platform injects through the `navigationEnd` slot; the workbench
// itself has no notion of an account.

import {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
import {
  appendSlot, attachMountRootClass,
  createUnmountHandle, detachMountedSlots, materializeSlots,
  renderCapabilityActions,
  validateMountRoot,
} from "./mount-options.js";
import {
  buildUniverseRoute,
  createScopePicker,
  knownProjectId,
  NAV,
  navEntry,
  parseUniverseRoute,
  renderStubView,
  SCOPE_NONE,
  scopeForEntry,
  universeNavScope,
} from "./universe_navigation.js";
import {
  DETAIL_RENDERERS, section, VIEW_RENDERERS,
} from "./universe_views.js";

export {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
export { buildUniverseRoute, parseUniverseRoute, universeNavScope };

const WORDMARK_ASSET_URL = new URL("./yoke-wordmark.svg", import.meta.url);

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function callFunction(client, functionId, payload, target) {
  const request = { function: functionId, payload: payload || {} };
  // Preserve the local proxy envelope: omit target unless a view supplies
  // one, so global-target reads keep their server-side default.
  if (target) request.target = target;
  return client.call(request);
}

// Whoever the viewer is acting as. The engine models an actor as an id and a
// kind and nothing else — a human actor has no name there, because a name
// belongs to an account and accounts are the host's. So the chip shows the
// host's label when it has one and falls back to the id, which is the only
// thing the universe itself knows.
function createActorChip(documentNode, actor) {
  const chip = el(documentNode, "span", "actor-chip");
  const name = actor.label || `actor ${actor.id}`;
  chip.appendChild(el(documentNode, "span", "actor-name", name));
  // A system actor is not a person, and a screen that lets the two look alike
  // invites reading automated work as somebody's.
  if (actor.kind === "system") {
    chip.appendChild(el(
      documentNode, "span", "actor-kind",
      actor.systemComponent || "system",
    ));
  }
  return chip;
}

// The way back out of a drill-in, naming the view it belongs to. It carries
// the view's project so returning lands on the same rows the row came from.
function createBreadcrumb(documentNode, entry, project, detail) {
  const bar = el(documentNode, "div", "breadcrumb");
  const back = el(documentNode, "a", "breadcrumb-parent", entry.label);
  back.href = buildUniverseRoute(entry.id, project);
  bar.appendChild(back);
  bar.appendChild(el(documentNode, "span", "breadcrumb-sep", "/"));
  bar.appendChild(el(documentNode, "span", "breadcrumb-here", String(detail)));
  return bar;
}

function emptyUniversePanel(documentNode) {
  const panel = section(documentNode, "Universe");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => {
      body.appendChild(el(
        documentNode, "p", "empty", "no projects yet",
      ));
    },
  );
  return panel;
}

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
  const resolvedSlots = materializeSlots(slots, rootNode);
  const mountedSlotNodes = [];
  let mounted = true;
  let projects = [];
  const context = {
    client,
    document: documentNode,
    isMounted: () => mounted,
    // The roster the scope pickers already hold, so a view that only lists
    // projects costs no second call.
    projects: () => projects,
  };

  const brand = el(documentNode, "div", "brand yoke-header-brand");
  brand.style.color = "var(--yoke-ink)";
  const orgContext = el(documentNode, "span", "org-context", "…");
  const contextSide = el(documentNode, "div", "context-side yoke-header-context");
  const capabilityActions = renderCapabilityActions(
    documentNode, capabilities,
  );
  if (capabilityActions) contextSide.appendChild(capabilityActions);
  // A host with a sign-in door names the viewer; a local universe admits a
  // loopback token rather than an actor, so it supplies none and the chip is
  // simply absent — never a greyed-out chip that names nobody.
  if (options.currentActor) {
    contextSide.appendChild(createActorChip(documentNode, options.currentActor));
  }
  contextSide.appendChild(orgContext);
  const header = el(documentNode, "header", "topbar yoke-app-header");
  appendSlot(header, resolvedSlots.topbarStart, mountedSlotNodes);
  header.appendChild(brand);
  header.appendChild(contextSide);
  appendSlot(header, resolvedSlots.topbarEnd, mountedSlotNodes);

  const navEl = el(documentNode, "nav", "sidenav");
  const main = el(documentNode, "main", "content");
  const shell = el(documentNode, "div", "shell");
  appendSlot(navEl, resolvedSlots.navigationStart, mountedSlotNodes);
  shell.appendChild(navEl);
  appendSlot(shell, resolvedSlots.contentBefore, mountedSlotNodes);
  shell.appendChild(main);
  appendSlot(shell, resolvedSlots.contentAfter, mountedSlotNodes);

  const navLinks = new Map();
  for (const entry of NAV) {
    const link = el(documentNode, "a", "nav-link", entry.label);
    navLinks.set(entry.id, link);
    navEl.appendChild(link);
  }
  appendSlot(navEl, resolvedSlots.navigationEnd, mountedSlotNodes);

  const detachRootClass = attachMountRootClass(rootNode);
  rootNode.replaceChildren(header, shell);

  // The mark uses currentColor, so it must live in the DOM (an <img src>
  // would not inherit color); the brand container's ink flips in dark mode.
  Promise.resolve().then(() => globalThis.fetch(WORDMARK_ASSET_URL))
    .then((response) => response.text())
    .then((svg) => { if (mounted) brand.innerHTML = svg; })
    .catch(() => { if (mounted) brand.textContent = "Yoke"; });

  Promise.resolve().then(() => callFunction(client, "organizations.get", {}))
    .then((callResult) => {
      if (!mounted) return;
      const org = (callResult.envelope && callResult.envelope.result) || {};
      orgContext.textContent = org.name || "(unnamed org)";
    })
    .catch(() => { if (mounted) orgContext.textContent = ""; });

  // Each visited scoped view remembers its own project.
  const scopeSelections = new Map();

  function renderRoute() {
    const route = parseUniverseRoute(windowNode.location.hash);
    const entry = navEntry(route.view);
    const project = scopeForEntry(
      entry, route.project, projects, scopeSelections,
    );

    for (const navItem of NAV) {
      const link = navLinks.get(navItem.id);
      link.href = buildUniverseRoute(
        navItem.id,
        navItem.scope === SCOPE_NONE
          ? null
          : (knownProjectId(
            projects, scopeSelections.get(navItem.id),
          ) || project),
      );
      link.classList.toggle("active", navItem.id === entry.id);
    }

    const detailRenderer = route.detail ? DETAIL_RENDERERS[entry.id] : null;
    const renderer = VIEW_RENDERERS[entry.id];
    if (!renderer) {
      renderStubView(context, main, entry);
      return;
    }
    if (entry.scope === SCOPE_NONE) {
      renderer(context, main, null);
      return;
    }
    if (project === null) {
      main.replaceChildren(emptyUniversePanel(documentNode));
      return;
    }
    if (detailRenderer) {
      // A drill-in swaps the view's picker for a breadcrumb: re-scoping a
      // single row to another project is nonsense, and the way out is back.
      const detailHost = el(documentNode, "div", "view-host");
      main.replaceChildren(
        createBreadcrumb(documentNode, entry, project, route.detail),
        detailHost,
      );
      detailRenderer(context, detailHost, project, route.detail);
      return;
    }
    // The picker is the view's own chrome, so it sits in the content column
    // above a host the view owns outright and re-renders into at will.
    const viewHost = el(documentNode, "div", "view-host");
    main.replaceChildren(createScopePicker({
      documentNode, entry, project, projects, renderRoute, scopeSelections,
      windowNode,
    }), viewHost);
    renderer(context, viewHost, project);
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
    detachMountedSlots(rootNode, mountedSlotNodes);
    rootNode.replaceChildren();
    detachRootClass();
  });
}
