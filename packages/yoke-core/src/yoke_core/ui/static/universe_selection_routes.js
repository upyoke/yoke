import { buildUniverseRoute, navEntry, parseUniverseRoute, SCOPE_SINGLE } from "./universe_navigation.js";
import { selectionParam } from "./universe_project_selection.js";

// Ordinary navigation preserves selection. A detail's project still addresses
// its resource; an explicit selection on a deep link remains authoritative.
export function withProjectSelection(hash, selection) {
  if (!String(hash).startsWith("#/")) return hash;
  const route = parseUniverseRoute(hash);
  if (route.selection !== null) return hash;
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  if (route.detail || navEntry(route.view).scope === SCOPE_SINGLE) {
    params.set("selection", selectionParam(selection));
  } else if (route.project === null) {
    params.set("project", selectionParam(selection));
  }
  return `${path}?${params.toString().replace(/%2C/g, ",")}`;
}

export function selectionRoute(route, state, project = null, sourceHash = "") {
  const focusRoute = route.detail || navEntry(route.view).scope === SCOPE_SINGLE;
  const hash = buildUniverseRoute(
    route.view, focusRoute ? project : selectionParam(state.selection), route.detail,
  );
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(sourceHash.split("?")[1] || "");
  params.delete("project");
  params.delete("selection");
  for (const [key, value] of new URLSearchParams(query)) params.set(key, value);
  if (focusRoute) params.set("selection", selectionParam(state.selection));
  return `${path}?${params.toString().replace(/%2C/g, ",")}`;
}

export function createSelectionNavigation(root, windowNode, state) {
  const authoredLinks = new WeakMap();
  const navigate = (hash) => {
    windowNode.location.hash = withProjectSelection(hash, state.selection);
  };
  // A capture listener also covers host-owned anchors and modified clicks.
  // The observer makes copied/open-in-new-tab links carry the same context.
  function rewrite(anchor) {
    const href = anchor.getAttribute?.("href") || anchor.href;
    if (!href || !href.startsWith("#/")) return;
    const previous = authoredLinks.get(anchor);
    const authored = previous?.rendered === href ? previous.authored : href;
    const next = withProjectSelection(authored, state.selection);
    authoredLinks.set(anchor, { authored, rendered: next });
    if (next !== href) anchor.setAttribute("href", next);
  }
  function activate(event) {
    if (event.defaultPrevented) return;
    if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
    if (event.type === "click" && event.button > 0) return;
    for (let node = event.target; node && node !== root; node = node.parentNode) {
      if (node.tagName === "A") { rewrite(node); return; }
      if (["BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME"].includes(node.tagName)) return;
      if (node.getAttribute?.("role") === "link") {
        const anchor = node.querySelector?.("a[href]");
        if (!anchor) return;
        rewrite(anchor);
        const href = anchor.getAttribute("href");
        if (!href?.startsWith("#/")) return;
        event.preventDefault();
        event.stopPropagation();
        navigate(href);
        return;
      }
    }
  }
  const observer = windowNode.MutationObserver ? new windowNode.MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "attributes") rewrite(record.target);
      for (const node of record.addedNodes || []) {
        if (node.tagName === "A") rewrite(node);
        for (const anchor of node.querySelectorAll?.("a[href]") || []) rewrite(anchor);
      }
    }
  }) : null;
  observer?.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
  root.addEventListener("click", activate, true);
  root.addEventListener("keydown", activate, true);
  return {
    navigate,
    refresh() {
      for (const anchor of root.querySelectorAll?.("a[href]") || []) rewrite(anchor);
    },
    replace(hash) {
      if (windowNode.location.hash === hash) return;
      if (windowNode.history?.replaceState) {
        windowNode.history.replaceState(windowNode.history.state, "", hash);
      } else windowNode.location.hash = hash;
    },
    dispose() {
      observer?.disconnect();
      root.removeEventListener("click", activate, true);
      root.removeEventListener("keydown", activate, true);
    },
  };
}
