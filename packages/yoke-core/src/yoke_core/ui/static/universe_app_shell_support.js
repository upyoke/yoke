import { callFunction } from "./universe_view_support.js";
import { createScopePicker, SCOPE_MULTI, SCOPE_NONE, SCOPE_SINGLE } from "./universe_navigation.js";
import { selectionRoute } from "./universe_selection_routes.js";

// A denied or failed write resolves normally with `success=false`; it must
// still reach `createProjectSelection`'s `saveFor` as a rejection, or a save
// that never landed would silently look saved.
export function saveScreenSelection(client, viewId, selection, focus) {
  return Promise.resolve(callFunction(
    client, "ui_preferences.screen_selection.set", { view_id: viewId, selection, focus },
  )).then((callResult) => {
    if (!callResult.envelope?.success) {
      throw new Error(callResult.envelope?.error?.message || "screen selection save failed");
    }
  });
}

// Each screen's remembered selection, seeded from the server before the
// first render so no screen ever paints then jumps. A failure here is not
// load-bearing the way `projects.list` is: every screen simply starts at
// "all" — but `markReady()` runs only on a genuine success, so normalization
// during that degraded render never persists a default over whatever the
// server actually still holds. The person still needs to know their choices
// are not being saved this session, so a failure surfaces the same scope
// notice a failed save does.
export function loadScreenSelections(client, scopeSelections) {
  return Promise.resolve().then(() => callFunction(
    client, "ui_preferences.screen_selection.list", {},
  )).then((callResult) => {
    if (!callResult.envelope?.success) {
      throw new Error(callResult.envelope?.error?.message || "screen selection list failed");
    }
    const views = callResult.envelope.result?.views || {};
    for (const [viewId, view] of Object.entries(views)) {
      scopeSelections.seed(viewId, view.selection, view.focus);
    }
    scopeSelections.markReady();
  }).catch(() => {
    // The mount bootstrap's own pending first render already reads
    // `notice` fresh once this settles — no re-render trigger needed here,
    // and firing one would race that render with a premature, incomplete one.
    scopeSelections.seedNotice("Couldn't load saved projects. Reload to retry.");
  });
}

export function createProjectControls(deps) {
  const { documentNode, windowNode, entry, route, scope, projects,
    scopeSelections, onSelectionChange, renderRoute } = deps;
  const picker = createScopePicker({
    documentNode, windowNode, entry: { ...entry, scope: SCOPE_MULTI },
    scope: scopeSelections.selectionFor(entry.id), projects, scopeSelections,
    onSelect: onSelectionChange,
  });
  if (entry.scope === SCOPE_SINGLE && !route.detail) {
    const focus = createScopePicker({
      documentNode, windowNode, entry, scope, projects, scopeSelections,
      onSelect(next) {
        scopeSelections.setFocusFor(entry.id, next);
        scopeSelections.saveFor(entry.id);
        windowNode.location.hash = selectionRoute(route, scopeSelections, next, windowNode.location.hash);
        renderRoute();
      },
    });
    const label = focus.children[0];
    label.textContent = "Focus project";
    picker.appendChild(focus);
  }
  if (entry.scope === SCOPE_NONE || scopeSelections.notice) {
    const note = documentNode.createElement("span");
    note.className = "scope-context-note";
    note.textContent = scopeSelections.notice || "Selection remembered · universe-wide view";
    picker.appendChild(note);
  }
  return picker;
}

export function revealActiveCompactDestination(windowNode, link) {
  if (
    !link ||
    typeof link.scrollIntoView !== "function" ||
    typeof windowNode.getComputedStyle !== "function"
  ) return;
  const navigation = link.parentNode;
  if (
    !navigation ||
    windowNode.getComputedStyle(navigation).flexDirection !== "row"
  ) return;
  link.scrollIntoView({ block: "nearest", inline: "nearest" });
}

export function loadWordmark(brand, assetUrl, isMounted) {
  Promise.resolve().then(() => globalThis.fetch(assetUrl))
    .then((response) => response.text())
    .then((svg) => { if (isMounted()) brand.innerHTML = svg; })
    .catch(() => { if (isMounted()) brand.textContent = "Yoke"; });
}

export function loadOrganizationName(client, orgContext, isMounted) {
  if (!orgContext) return;
  Promise.resolve().then(() => callFunction(client, "organizations.get", {}))
    .then((callResult) => {
      if (!isMounted()) return;
      const org = (callResult.envelope && callResult.envelope.result) || {};
      orgContext.textContent = org.name || "(unnamed org)";
    })
    .catch(() => { if (isMounted()) orgContext.textContent = ""; });
}

export function createHostSectionPlacement(resolvedSections) {
  function append(entry, viewHost, { scoped = false } = {}) {
    const hostSection = resolvedSections[entry.id];
    if (!hostSection) return;
    if (scoped && hostSection.placement === "beforeScope") return;
    viewHost.appendChild(hostSection.content);
  }

  function beforeScope(entry) {
    const hostSection = resolvedSections[entry.id];
    return (hostSection && hostSection.placement === "beforeScope")
      ? [hostSection.content] : [];
  }

  return { append, beforeScope };
}

// Owns the one scoped view that repaints in place from held data (the
// Overview). A held view registers a `rescope` handle; a project-selection
// change repaints it (no refetch, no full route render) and refreshes the nav
// hrefs. Every other scope change — and any view/tab/detail change — falls
// through to the caller's `renderRoute`, which rebuilds and refetches.
export function createHeldScopeController(deps) {
  const {
    windowNode, scopeSelections, renderRoute, projectsRef,
    navEntry, serializeScope, parseUniverseRoute,
    navLinks, nav, buildUniverseRoute, rememberedScopeParam, resolveRoute, refreshLinks,
  } = deps;
  let active = null;
  function refreshNavHrefs(activeId) {
    for (const navItem of nav) {
      const link = navLinks.get(navItem.id);
      if (!link) continue;
      link.href = navItem.scope === SCOPE_SINGLE
        ? selectionRoute({ view: navItem.id }, scopeSelections, scopeSelections.focusFor(navItem.id))
        : buildUniverseRoute(
        navItem.id,
        rememberedScopeParam(navItem, projectsRef(), scopeSelections),
        );
      link.classList.toggle("active", navItem.id === activeId);
    }
    revealActiveCompactDestination(windowNode, navLinks.get(activeId));
    refreshLinks?.();
  }
  function reset() { active = null; }
  function register(viewId, scope, picker, handle) {
    active = handle && typeof handle.rescope === "function"
      ? { viewId, currentScope: scope, picker, rescope: handle.rescope }
      : null;
  }
  function applyScopeInPlace(next) {
    if (!active) { renderRoute(); return; }
    active.currentScope = next;
    active.picker.setScope(next);
    active.rescope(next);
    refreshNavHrefs(active.viewId);
  }
  function onHashChange() {
    const route = parseUniverseRoute(windowNode.location.hash);
    if (active && active.viewId === route.view && !route.detail && !route.tab) {
      const entry = navEntry(route.view);
      const next = resolveRoute(route, entry);
      // A chip click already applied this scope directly; the browser's
      // follow-on hashchange is a no-op. A different hash (direct edit /
      // back-forward) rescopes in place, still with no refetch.
      if (serializeScope(next) === serializeScope(active.currentScope)) return;
      applyScopeInPlace(next);
      return;
    }
    renderRoute();
  }
  return { refreshNavHrefs, reset, register, applyScopeInPlace, onHashChange };
}
