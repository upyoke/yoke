// Keep destination code out of the mount shell's initial module graph.
import { el } from "./universe_view_support.js";

export function deferredRenderer(load, name) {
  return (context, host, ...args) => {
    const signal = context.signal;
    const current = () => context.isMounted() && !signal?.aborted;
    const loading = el(context.document, "p", "item-roster-note", "Loading screen…");
    loading.setAttribute("role", "status");
    host.appendChild(loading);
    return Promise.resolve().then(load).then((module) => {
      if (!current()) return null;
      loading.parentNode?.removeChild(loading);
      return module[name](context, host, ...args);
    }).catch(() => {
      if (current()) host.replaceChildren(el(context.document, "p", "error",
        "view_module_load_failed: This screen could not be loaded. Reload to retry."));
      return null;
    });
  };
}
