// Native history restores before an asynchronous route has grown back to its
// previous height. Keep the position on the entry and finish when content fits.
const POSITION_KEY = "universeDocumentScroll";

export function attachDocumentScroll(root, windowNode) {
  const history = windowNode.history;
  if (!history || !("scrollRestoration" in history)) return () => {};
  const previous = history.scrollRestoration;
  history.scrollRestoration = "manual";
  let pending = history.state?.[POSITION_KEY] || null;
  let frame = null;
  const remember = () => {
    if (pending) return;
    history.replaceState({ ...history.state, [POSITION_KEY]: {
      x: windowNode.scrollX, y: windowNode.scrollY,
    } }, "");
  };
  const restore = () => {
    if (!pending) return;
    windowNode.scrollTo(pending.x, pending.y);
    if (Math.abs(windowNode.scrollY - pending.y) < 1) pending = null;
  };
  const schedule = () => {
    if (frame !== null) windowNode.cancelAnimationFrame(frame);
    frame = windowNode.requestAnimationFrame(() => { frame = null; restore(); });
  };
  const onEntry = (event) => {
    pending = event.state?.[POSITION_KEY] || { x: 0, y: 0 };
    schedule();
  };
  const cancelRestore = () => { pending = null; };
  const observer = new windowNode.ResizeObserver(schedule);
  observer.observe(root);
  windowNode.addEventListener("popstate", onEntry);
  windowNode.addEventListener("scroll", remember, { passive: true });
  for (const event of ["wheel", "touchstart", "keydown"]) {
    windowNode.addEventListener(event, cancelRestore, { passive: true });
  }
  schedule();
  return () => {
    observer.disconnect();
    if (frame !== null) windowNode.cancelAnimationFrame(frame);
    history.scrollRestoration = previous;
    windowNode.removeEventListener("popstate", onEntry);
    windowNode.removeEventListener("scroll", remember);
    for (const event of ["wheel", "touchstart", "keydown"]) {
      windowNode.removeEventListener(event, cancelRestore);
    }
  };
}
