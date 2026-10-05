import { createPathNavigation } from "./universe_path_navigation.js";
import { buildUniverseRoute, navEntry, parseUniverseRoute, SCOPE_SINGLE, routeHref } from "./universe_navigation.js";
import { selectionParam } from "./universe_project_selection.js";

// Ordinary navigation preserves selection — each destination's OWN
// remembered selection, looked up by the href's own view, never the
// selection of whichever screen the link happens to be rewritten from. A
// detail's project still addresses its resource; an explicit selection on a
// deep link remains authoritative.
export function withProjectSelection(href, selections, basePath = "") {
  href = routeHref(href, basePath) || href;
  if (!routeHref(href, basePath)) return href;
  const route = parseUniverseRoute(href, basePath);
  if (route.selection !== null) return href;
  const selection = selections.selectionFor(route.view);
  const [path, query = ""] = href.split("?");
  const params = new URLSearchParams(query);
  if (route.detail || navEntry(route.view).scope === SCOPE_SINGLE) {
    params.set("selection", selectionParam(selection));
  } else if (route.project === null) {
    params.set("project", selectionParam(selection));
  }
  return `${path}?${params.toString().replace(/%2C/g, ",")}`;
}

export function selectionRoute(route, selections, project = null, sourceHref = "") {
  const focusRoute = route.detail || navEntry(route.view).scope === SCOPE_SINGLE;
  const selection = selections.selectionFor(route.view);
  // A tabbed destination spends its first path segment on the tab, so the
  // drill-in has to travel in the second one. Rebuilding with the drill-in in
  // the tab slot silently dropped the tab: a scope change on a run page
  // rewrote `/deployments/runs/<run id>` to `/deployments/<run id>`, which
  // still rendered the run and still lost the tab its breadcrumb returns to.
  const href = buildUniverseRoute(
    route.view,
    focusRoute ? project : selectionParam(selection),
    route.tab || route.detail,
    route.tab ? route.detail : null,
  );
  const [path, query = ""] = href.split("?");
  const params = new URLSearchParams(sourceHref.split("?")[1] || "");
  params.delete("project");
  params.delete("selection");
  for (const [key, value] of new URLSearchParams(query)) params.set(key, value);
  if (focusRoute) params.set("selection", selectionParam(selection));
  return `${path}?${params.toString().replace(/%2C/g, ",")}`;
}

export function createSelectionNavigation(root, windowNode, state, basePath = "") {
  const authoredLinks = new WeakMap();
  const paths = createPathNavigation(windowNode, basePath);
  const navigate = (href, options) => paths.navigate(withProjectSelection(href, state, basePath), options);
  // A capture listener also covers host-owned anchors and modified clicks.
  // The observer makes copied/open-in-new-tab links carry the same context.
  function rewrite(anchor) {
    const href = anchor.getAttribute?.("href") || anchor.href;
    if (!routeHref(href, basePath)) return;
    const previous = authoredLinks.get(anchor);
    const authored = previous?.rendered === href ? previous.authored : href;
    const next = withProjectSelection(authored, state, basePath);
    authoredLinks.set(anchor, { authored, rendered: next });
    if (next !== href) anchor.setAttribute("href", next);
  }
  function activate(event) {
    if (event.defaultPrevented) return;
    if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
    if (event.type === "click" && (event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
    for (let node = event.target; node && node !== root; node = node.parentNode) {
      if (node.tagName === "A") { rewrite(node); return; }
      if (["BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME"].includes(node.tagName)) return;
      if (node.getAttribute?.("role") === "link") {
        const anchor = node.querySelector?.("a[href]");
        if (!anchor) return;
        rewrite(anchor);
        const href = anchor.getAttribute("href");
        if (!routeHref(href, basePath)) return;
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
  const followAnchor = (event) => {
    if (event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target?.closest?.("a[href]");
    if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
    const href = anchor.getAttribute("href");
    if (!routeHref(href, basePath)) return;
    event.preventDefault();
    navigate(href);
  };
  root.addEventListener("click", followAnchor);
  root.addEventListener("click", activate, true);
  root.addEventListener("keydown", activate, true);
  return {
    ...paths, navigate,
    refresh() {
      for (const anchor of root.querySelectorAll?.("a[href]") || []) rewrite(anchor);
    },
    dispose() {
      observer?.disconnect();
      root.removeEventListener("click", followAnchor);
      root.removeEventListener("click", activate, true);
      root.removeEventListener("keydown", activate, true);
    },
  };
}
