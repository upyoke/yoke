// Mount-local host pages share the section node validator and view AbortSignal.
import { NAV, MOVED_VIEWS } from "./universe_destinations.js";
import { hostNavEntries } from "./universe_navigation.js";
import { materializeSections } from "./mount-options.js";
import { createPageHead, el } from "./universe_app_chrome.js";

export function createHostPages(navigation = [], rootNode, seen = new Set()) {
  const reserved = new Set([...NAV.map((entry) => entry.id), ...Object.keys(MOVED_VIEWS)]);
  const ids = new Set(), groups = new Set();
  const refuse = (code, id, recovery) => {
    throw new TypeError(`${code}: ${String(id)}. ${recovery}`);
  };
  for (const group of navigation) {
    if (!/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(group.id) || groups.has(group.id)) {
      refuse("host_group_id_invalid", group.id, "Use a unique lowercase slug for each host group and remount.");
    }
    groups.add(group.id);
    for (const page of group.pages) {
      if (reserved.has(page.id)) {
        refuse("host_page_id_reserved", page.id, "Choose a page id distinct from Yoke views and remount.");
      }
      if (!/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(page.id) || ids.has(page.id)) {
        refuse("host_page_id_invalid", page.id, "Use a unique lowercase slug for each host page and remount.");
      }
      ids.add(page.id);
    }
  }
  const entries = hostNavEntries(navigation);
  const sections = materializeSections(Object.fromEntries(
    entries.map((page) => [page.id, page.content]),
  ), rootNode, seen);
  let current = null;
  function clear() {
    if (current) {
      const node = current.content;
      if (node?.parentNode) node.parentNode.removeChild(node);
      current.release(current.content);
      if (current.render) current.content = null;
      current = null;
    }
  }
  return {
    entries,
    clear,
    render(entry, route, main, context, universeId = null) {
      if (!entry.hostPage) return false;
      const documentNode = rootNode.ownerDocument;
      const body = el(documentNode, "div", "view-host");
      main.replaceChildren(createPageHead(documentNode, entry), body);
      current = sections[entry.id];
      try {
        if (current?.render) current.content = current.render({
          universeId, scope: null, projectSelection: "all", signal: context.signal,
          detail: route.detail,
        });
        if (current?.content) body.appendChild(current.content);
      } catch (error) {
        context.abortView?.();
        body.replaceChildren(el(documentNode, "p", "error-banner",
          `host_page_render_failed: ${error?.message || String(error)}. Fix the host page factory and reload to retry.`));
      }
      return true;
    },
  };
}
