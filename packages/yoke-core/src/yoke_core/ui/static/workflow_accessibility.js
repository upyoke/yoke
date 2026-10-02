const dialogStates = new WeakMap();

const CONTROL_TAGS = new Set(["BUTTON", "INPUT", "SELECT", "TEXTAREA"]);

function attribute(node, name) {
  if (typeof node?.getAttribute === "function") {
    return node.getAttribute(name);
  }
  return node?.attributes?.get?.(name) ?? null;
}

function descendants(node) {
  return [
    ...(node?.children || []),
  ].flatMap((child) => [child, ...descendants(child)]);
}

function focusableControls(dialog) {
  return descendants(dialog).filter((node) => {
    if (node.hidden || node.disabled || attribute(node, "tabindex") === "-1") {
      return false;
    }
    if (CONTROL_TAGS.has(node.tagName)) return true;
    if (node.tagName === "A") {
      return Boolean(node.href || attribute(node, "href"));
    }
    return Number(node.tabIndex) >= 0;
  });
}

function focus(node) {
  if (typeof node?.focus === "function") node.focus();
}

export function workflowDomId(value) {
  return String(value).replace(/[^A-Za-z0-9_-]/g, "-");
}

export function linkWorkflowPanel(content, workflowId) {
  const domId = workflowDomId(workflowId);
  content.setAttribute("role", "tabpanel");
  content.setAttribute("id", `workflow-panel-${domId}`);
  content.setAttribute("aria-labelledby", `workflow-tab-${domId}`);
}

function dialogIsBusy(dialog) {
  return attribute(dialog, "aria-busy") === "true";
}

export function releaseWorkflowDialog(host, { restoreFocus = true } = {}) {
  const state = dialogStates.get(host);
  if (!state) return;
  state.eventTarget?.removeEventListener("keydown", state.keydown);
  state.observer?.disconnect();
  dialogStates.delete(host);
  if (restoreFocus && state.opener?.isConnected !== false &&
    state.root.contains(state.opener)) focus(state.opener);
}

export function clearWorkflowDialog(host) {
  releaseWorkflowDialog(host);
  host.replaceChildren();
}

export function mountWorkflowDialog({
  documentNode,
  host,
  dialog,
  dismiss,
  initialFocus = null,
}) {
  if (dialog.isConnected === false) return () => {};
  const existing = dialogStates.get(host);
  const opener = existing?.opener || documentNode.activeElement || null;
  if (existing) releaseWorkflowDialog(host, { restoreFocus: false });

  const eventTarget = documentNode.defaultView || documentNode;
  // A route can remove the entire dialog without taking its explicit close
  // path. Release global listeners then, without moving focus off the new page.
  let root = host;
  while (root.parentNode) root = root.parentNode;
  const isMounted = () => dialog.isConnected !== false &&
    root.contains(dialog) && host.contains(dialog);
  const releaseDetached = () => {
    if (isMounted()) return false;
    releaseWorkflowDialog(host, { restoreFocus: false });
    return true;
  };
  const keydown = (event) => {
    // Mutation observers run after DOM changes; a key may arrive first.
    if (releaseDetached()) return;
    if (event.key === "Escape") {
      if (dialogIsBusy(dialog)) return;
      event.preventDefault();
      dismiss();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = focusableControls(dialog);
    if (!controls.length) return;
    const current = controls.indexOf(documentNode.activeElement);
    const direction = event.shiftKey ? -1 : 1;
    const next = current < 0
      ? (event.shiftKey ? controls.length - 1 : 0)
      : (current + direction + controls.length) % controls.length;
    event.preventDefault();
    focus(controls[next]);
  };
  const Observer = documentNode.defaultView?.MutationObserver;
  const observer = Observer ? new Observer(releaseDetached) : null;
  eventTarget?.addEventListener("keydown", keydown);
  dialogStates.set(host, { eventTarget, keydown, opener, root, observer });
  observer?.observe(root, { childList: true, subtree: true });
  focus(initialFocus || focusableControls(dialog)[0]);
  return () => releaseWorkflowDialog(host, { restoreFocus: false });
}
