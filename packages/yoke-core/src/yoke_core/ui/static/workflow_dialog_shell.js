import { el } from "./universe_view_support.js";
import {
  mountWorkflowDialog,
} from "./workflow_accessibility.js";
import {
  button,
} from "./workflow_view_primitives.js";

function dialogIsBusy(dialog) {
  return dialog.attributes?.get?.("aria-busy") === "true" ||
    dialog.getAttribute?.("aria-busy") === "true";
}

export function workflowDialogShell(documentNode, host, title, close) {
  host.replaceChildren();
  const backdrop = el(documentNode, "div", "workflow-dialog-backdrop");
  const dialog = el(
    documentNode, "section",
    "workflow-dialog workflow-mechanics-dialog",
  );
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", title);
  dialog.appendChild(el(
    documentNode, "h2", "workflow-dialog-title", title,
  ));
  backdrop.appendChild(dialog);
  const dismiss = () => {
    if (dialogIsBusy(dialog)) return;
    close();
  };
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) dismiss();
  });
  host.appendChild(backdrop);
  return {
    dialog,
    dismiss,
    activate(initialFocus) {
      mountWorkflowDialog({
        documentNode,
        host,
        dialog,
        dismiss,
        initialFocus,
      });
    },
  };
}

export function appendWorkflowDialogFooter(documentNode, dialog, {
  impact = "", confirmText, dismiss, activate, save, disabled = false,
}) {
  const error = el(documentNode, "p", "workflow-dialog-error");
  error.hidden = true;
  error.setAttribute("role", "alert");
  dialog.appendChild(error);
  const row = el(documentNode, "div", "workflow-dialog-footer");
  if (!impact) row.classList.add("actions-only");
  if (impact) {
    row.appendChild(el(
      documentNode, "p", "workflow-dialog-impact", impact,
    ));
  }
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = button(documentNode, "Cancel");
  const confirm = button(
    documentNode, confirmText, "workflow-button primary",
  );
  confirm.disabled = disabled;
  cancel.addEventListener("click", dismiss);
  confirm.addEventListener("click", async () => {
    cancel.disabled = true;
    confirm.disabled = true;
    dialog.setAttribute("aria-busy", "true");
    confirm.textContent = "Saving…";
    error.hidden = true;
    try {
      await save();
    } catch (failure) {
      cancel.disabled = false;
      confirm.disabled = disabled;
      dialog.setAttribute("aria-busy", "false");
      confirm.textContent = confirmText;
      error.textContent = String(failure?.message || failure);
      error.hidden = false;
    }
  });
  actions.appendChild(cancel);
  actions.appendChild(confirm);
  row.appendChild(actions);
  dialog.appendChild(row);
  activate(cancel);
}
