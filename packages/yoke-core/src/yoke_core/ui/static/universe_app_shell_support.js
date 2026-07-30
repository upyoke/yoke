import { callFunction } from "./universe_view_support.js";

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
    navEntry, scopeForEntry, serializeScope, parseUniverseRoute,
    navLinks, nav, buildUniverseRoute, rememberedScopeParam,
  } = deps;
  let active = null;
  function refreshNavHrefs(activeId) {
    for (const navItem of nav) {
      const link = navLinks.get(navItem.id);
      if (!link) continue;
      link.href = buildUniverseRoute(
        navItem.id,
        rememberedScopeParam(navItem, projectsRef(), scopeSelections),
      );
      link.classList.toggle("active", navItem.id === activeId);
    }
    revealActiveCompactDestination(windowNode, navLinks.get(activeId));
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
      const next = scopeForEntry(
        entry, route.project, projectsRef(), scopeSelections,
      );
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
