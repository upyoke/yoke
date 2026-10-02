// The sidebar is ordinary navigation on a wide screen and a modal drawer
// when its toggle is visible. Read that CSS decision so resize behavior and
// the stylesheet cannot acquire different breakpoints.

function controlsWithin(node, windowNode) {
  if (node.hidden || node.inert) return [];
  const style = windowNode.getComputedStyle?.(node);
  if (style?.display === "none" || style?.visibility === "hidden") return [];
  const controls = [...(node.children || [])].flatMap(
    (child) => controlsWithin(child, windowNode),
  );
  const control = !node.disabled && node.getAttribute?.("tabindex") !== "-1"
    && (["BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(node.tagName)
      || node.tagName === "A" && Boolean(node.href)
      || Number(node.tabIndex) >= 0);
  return control ? [node, ...controls] : controls;
}

export function attachNavigationDrawer({
  documentNode, header, shell, navigation, toggle, close, scrim,
  body, footer, main, links,
}) {
  const windowNode = documentNode.defaultView;
  let open = false;
  let disposed = false;
  const isNarrow = () => windowNode.getComputedStyle?.(toggle).display !== "none";
  const paint = () => {
    const narrow = isNarrow();
    if (!narrow) open = false;
    shell.classList.toggle("side-open", open);
    documentNode.body?.classList.toggle("side-open", open);
    navigation.inert = narrow && !open;
    for (const background of [header, body, footer]) background.inert = open;
    scrim.hidden = !open;
    scrim.tabIndex = -1;
    close.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    if (open) {
      navigation.setAttribute("role", "dialog");
      navigation.setAttribute("aria-modal", "true");
    } else {
      navigation.removeAttribute("role");
      navigation.removeAttribute("aria-modal");
    }
  };
  navigation.setAttribute("aria-label", "Navigation");
  const dismiss = ({ returnFocus = true } = {}) => {
    if (!open) return;
    open = false;
    paint();
    if (returnFocus && isNarrow()) toggle.focus?.();
  };
  const onToggle = () => {
    if (open) { dismiss(); return; }
    if (!isNarrow()) return;
    open = true;
    paint();
    close.focus?.();
  };
  const onDestination = () => {
    if (!open) return;
    dismiss({ returnFocus: false });
    main.tabIndex = -1;
    main.focus?.();
  };
  const onResize = () => {
    const active = documentNode.activeElement;
    paint();
    if (!open && active === close) controlsWithin(navigation, windowNode)[0]?.focus?.();
  };
  const onKeydown = (event) => {
    if (!open) return;
    if ((event.metaKey || event.ctrlKey) && String(event.key).toLowerCase() === "k") {
      dismiss({ returnFocus: false });
      return;
    }
    if (event.key === "Escape") { event.preventDefault(); dismiss(); return; }
    if (event.key !== "Tab") return;
    const controls = controlsWithin(navigation, windowNode);
    if (!controls.length) return;
    const index = controls.indexOf(documentNode.activeElement);
    const next = index < 0 ? (event.shiftKey ? controls.length - 1 : 0)
      : (index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
    event.preventDefault();
    controls[next].focus?.();
  };
  const onDismiss = () => dismiss();
  toggle.addEventListener("click", onToggle);
  close.addEventListener("click", onDismiss);
  scrim.addEventListener("click", onDismiss);
  for (const link of links.values()) link.addEventListener("click", onDestination);
  windowNode.addEventListener("keydown", onKeydown, true);
  windowNode.addEventListener("resize", onResize);
  // Chrome is constructed before it is attached. The first CSS measurement
  // must happen after mounting, otherwise detached styles guess the mode.
  queueMicrotask(() => { if (!disposed) paint(); });
  return () => {
    disposed = true;
    open = false;
    paint();
    navigation.inert = false;
    toggle.removeEventListener("click", onToggle);
    close.removeEventListener("click", onDismiss);
    scrim.removeEventListener("click", onDismiss);
    for (const link of links.values()) link.removeEventListener("click", onDestination);
    windowNode.removeEventListener("keydown", onKeydown, true);
    windowNode.removeEventListener("resize", onResize);
  };
}
