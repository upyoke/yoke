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
  dialogStates.delete(host);
  if (restoreFocus) focus(state.opener);
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
  const existing = dialogStates.get(host);
  const opener = existing?.opener || documentNode.activeElement || null;
  if (existing) releaseWorkflowDialog(host, { restoreFocus: false });

  const eventTarget = documentNode.defaultView || documentNode;
  const keydown = (event) => {
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
  eventTarget?.addEventListener("keydown", keydown);
  dialogStates.set(host, { eventTarget, keydown, opener });
  focus(initialFocus || focusableControls(dialog)[0]);
}
