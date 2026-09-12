// One dismissal contract for the transient surfaces the universe frame opens
// over its content: the actor menu, the cross-screen search results, and the
// footer panels. An open surface has to close on the three gestures a person
// actually makes — a click outside it, Escape, and going somewhere else — and
// the third is the one every hand-rolled menu forgets: the menu item IS a
// route link, so the content underneath navigates while the panel that
// started the navigation stays open over the new screen.
//
// The listeners live on the window rather than the document: one target for
// all three events, bubbling still covers every click inside the mount, and a
// harness whose document is not an event target keeps the behavior. Every
// surface hands back the returned dispose so an unmount leaves nothing behind.

// `trigger` may be the node that opened the surface or a function returning
// whichever of several triggers is currently open — Escape returns focus
// there, because a keyboard dismissal that drops focus to the document
// strands the person at the top of the page.
function focusTarget(trigger) {
  const node = typeof trigger === "function" ? trigger() : trigger;
  return typeof node?.focus === "function" ? node : null;
}

export function attachMenuDismissal(
  documentNode, { root, close, isOpen, trigger = null },
) {
  const windowNode = documentNode.defaultView;
  if (!windowNode) return () => {};
  const dismiss = (restoreFocus) => {
    if (!isOpen()) return;
    close();
    if (restoreFocus) focusTarget(trigger)?.focus();
  };
  const onClick = (event) => {
    if (root.contains(event.target)) return;
    dismiss(false);
  };
  const onKeydown = (event) => {
    if (event.key === "Escape") dismiss(true);
  };
  const onHashChange = () => dismiss(false);
  windowNode.addEventListener("click", onClick);
  windowNode.addEventListener("keydown", onKeydown);
  windowNode.addEventListener("hashchange", onHashChange);
  return () => {
    windowNode.removeEventListener("click", onClick);
    windowNode.removeEventListener("keydown", onKeydown);
    windowNode.removeEventListener("hashchange", onHashChange);
  };
}
