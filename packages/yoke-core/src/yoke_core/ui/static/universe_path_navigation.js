// One history owner for real navigation, entry canonicalization, and Back.
// History records route ancestry only; scroll state belongs to the browser.
import { normalizeRouteBase, parseUniverseRoute, routeHref } from "./universe_navigation.js";

export const ROUTE_NAVIGATION_EVENT = "yoke:navigate";
const HISTORY_KEY = "yokeDashboard";
export const currentRouteHref = (windowNode) =>
  `${windowNode.location.pathname}${windowNode.location.search || ""}`;

export function createPathNavigation(windowNode, basePath = "") {
  const base = normalizeRouteBase(basePath);
  const { history, location } = windowNode;
  const position = () => history.state?.[HISTORY_KEY]?.basePath === base
    ? history.state[HISTORY_KEY].position : 0;
  const stateAt = (index) => ({ ...history.state,
    [HISTORY_KEY]: { basePath: base, position: index },
  });
  // A bookmark's fragment query moves into the server-visible query once.
  if (location.hash?.startsWith("#/")) {
    const legacy = routeHref(location.hash.slice(1), base);
    if (legacy) history.replaceState(history.state, "", legacy);
  }
  history.replaceState(stateAt(position()), "", currentRouteHref(windowNode));
  function replace(href) {
    const next = routeHref(href, base);
    if (next && next !== currentRouteHref(windowNode)) {
      history.replaceState(stateAt(position()), "", next);
    }
  }
  function navigate(href, { projectSwitch = false } = {}) {
    const next = routeHref(href, base);
    if (!next || next === currentRouteHref(windowNode)) return;
    const before = parseUniverseRoute(currentRouteHref(windowNode), base);
    const after = parseUniverseRoute(next, base);
    history.pushState(stateAt(position() + 1), "", next);
    windowNode.dispatchEvent(new windowNode.Event(ROUTE_NAVIGATION_EVENT));
    if (projectSwitch || before.view !== after.view || before.tab !== after.tab ||
        before.detail !== after.detail || before.project !== after.project ||
        before.selection !== after.selection) windowNode.scrollTo(0, 0);
  }
  return {
    basePath: base, current: () => currentRouteHref(windowNode), replace, navigate,
    back(fallback) {
      if (position() > 0) history.back();
      else navigate(fallback);
    },
  };
}
