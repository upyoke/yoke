// One history owner for real navigation, entry canonicalization, and Back.
// History records route ancestry only; scroll state belongs to the browser.
// It also owns the document title: every history write names its screen
// first, because the page-view tracker reads the title as the URL changes,
// before any view renders.
import {
  navEntry, normalizeRouteBase, parseUniverseRoute, routeDocumentTitle, routeHref,
} from "./universe_navigation.js";

export const ROUTE_NAVIGATION_EVENT = "yoke:navigate";
const HISTORY_KEY = "yokeDashboard";
export const currentRouteHref = (windowNode) =>
  `${windowNode.location.pathname}${windowNode.location.search || ""}`;

export function createPathNavigation(windowNode, basePath = "", navigation = []) {
  const base = normalizeRouteBase(basePath);
  const { history, location } = windowNode;
  const current = () => {
    const href = currentRouteHref(windowNode);
    const entry = navEntry(parseUniverseRoute(href, base, navigation).view, navigation);
    return href + (entry.hostPage ? location.hash || "" : "");
  };
  const position = () => history.state?.[HISTORY_KEY]?.basePath === base
    ? history.state[HISTORY_KEY].position : 0;
  const stateAt = (index) => ({ ...history.state,
    [HISTORY_KEY]: { basePath: base, position: index },
  });
  const nameScreen = (href) => {
    windowNode.document.title = routeDocumentTitle(parseUniverseRoute(href, base, navigation), navigation);
  };
  // Back/Forward have already moved the URL; this listener precedes the
  // page-view tracker's because the tracker starts after mount.
  const onPopState = () => nameScreen(current());
  windowNode.addEventListener("popstate", onPopState);
  // A bookmark's fragment query moves into the server-visible query once.
  if (location.hash?.startsWith("#/")) {
    const legacy = routeHref(location.hash.slice(1), base, navigation);
    if (legacy) history.replaceState(history.state, "", legacy);
  }
  nameScreen(current());
  history.replaceState(stateAt(position()), "", current());
  function replace(href) {
    const next = routeHref(href, base, navigation);
    if (next && next !== current()) {
      nameScreen(next);
      history.replaceState(stateAt(position()), "", next);
    }
  }
  function navigate(href, { projectSwitch = false, replace = false } = {}) {
    const next = routeHref(href, base, navigation);
    if (!next || next === current()) return;
    const before = parseUniverseRoute(current(), base, navigation);
    const after = parseUniverseRoute(next, base, navigation);
    nameScreen(next);
    // Selection changes render normally while retaining the current ancestry.
    if (replace) history.replaceState(stateAt(position()), "", next);
    else history.pushState(stateAt(position() + 1), "", next);
    windowNode.dispatchEvent(new windowNode.Event(ROUTE_NAVIGATION_EVENT));
    if (projectSwitch || before.view !== after.view || before.tab !== after.tab ||
        before.detail !== after.detail || before.project !== after.project ||
        before.selection !== after.selection) windowNode.scrollTo(0, 0);
  }
  return {
    basePath: base, current, replace, navigate,
    back(fallback) {
      if (position() > 0) history.back();
      else navigate(fallback);
    },
    dispose() {
      windowNode.removeEventListener("popstate", onPopState);
    },
  };
}
