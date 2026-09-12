// One signal for the page coming back to the foreground, and the screens
// that re-read when it does.
//
// A laptop that sleeps leaves the dashboard holding the snapshot it had when
// the lid closed: the relay recovers, sessions end and machines go quiet,
// and the page keeps showing none of it until someone reloads by hand. A
// return to the foreground is the moment that snapshot is known to be old,
// so the screens showing live fleet state re-read then — the same read their
// own lifecycle already performs, against the same scope, leaving what is on
// screen in place until the new rows arrive.
//
// Not polling: nothing here runs on a timer, and a page left in the
// foreground is never re-read by this module.

// One return fires more than one event — `visibilitychange` then `focus`,
// in either order — and a person clicking between windows fires more. Within
// this window they are the same return, so the screens re-read once.
const REVISIT_COALESCE_MS = 1500;

export function createPageRevisit(documentNode, rootNode, isMounted) {
  const windowNode = documentNode.defaultView;
  const subscribers = new Set();
  let lastRevisit = 0;

  const revisited = () => {
    if (!isMounted()) return;
    // A `visibilitychange` also fires on the way OUT; only a page that is
    // actually showing has anything to refresh.
    if (documentNode.visibilityState === "hidden") return;
    const now = Date.now();
    if (now - lastRevisit < REVISIT_COALESCE_MS) return;
    lastRevisit = now;
    for (const entry of [...subscribers]) {
      // A screen the router has already replaced is gone from the mounted
      // tree: it drops out here rather than spending a read on nodes
      // nobody can see.
      if (!rootNode.contains(entry.host)) {
        subscribers.delete(entry);
        continue;
      }
      if (entry.running) continue;
      entry.running = true;
      Promise.resolve()
        .then(entry.refresh)
        .catch(() => {})
        .then(() => { entry.running = false; });
    }
  };

  documentNode.addEventListener?.("visibilitychange", revisited);
  windowNode?.addEventListener("focus", revisited);

  return {
    subscribe(host, refresh) {
      subscribers.add({ host, refresh, running: false });
    },
    dispose() {
      subscribers.clear();
      documentNode.removeEventListener?.("visibilitychange", revisited);
      windowNode?.removeEventListener("focus", revisited);
    },
  };
}
