import {
  callFunction,
  el,
} from "./universe_view_support.js";
import { mountWorkflowDialog, releaseWorkflowDialog } from "./workflow_accessibility.js";

function rejectedCallMessage(error, fallback) {
  if (error instanceof Error && error.message) return error.message;
  const detail = String(error ?? "").trim();
  return detail || fallback;
}

export function waiverDialog(context, row, reload) {
  const documentNode = context.document;
  const overlay = el(documentNode, "div", "qa-action-overlay");
  const dialog = el(documentNode, "section", "qa-action-dialog");
  let busy = false;
  const close = () => {
    if (busy) return;
    releaseWorkflowDialog(overlay);
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
  };
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", `Waive ${row.case_key}`);
  overlay.addEventListener("click", close);
  dialog.addEventListener("click", (event) => event.stopPropagation());
  dialog.appendChild(el(
    documentNode, "h2", null, `Waive ${row.case_key}?`,
  ));
  dialog.appendChild(el(
    documentNode,
    "p",
    "muted",
    "A waiver authorizes progress without asserting that the case passed. The rationale is retained with the requirement.",
  ));
  const rationale = el(documentNode, "textarea", "qa-waiver-rationale");
  rationale.placeholder = "Why is proceeding without this proof acceptable?";
  const label = el(documentNode, "label", null, "Waiver rationale");
  label.appendChild(rationale);
  dialog.appendChild(label);
  const error = el(documentNode, "p", "qa-action-error");
  error.setAttribute("role", "alert");
  dialog.appendChild(error);
  const actions = el(documentNode, "div", "qa-action-dialog-buttons");
  const cancel = el(documentNode, "button", "btn", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  actions.appendChild(cancel);
  const confirm = el(documentNode, "button", "btn primary", "Waive case");
  confirm.type = "button";
  confirm.addEventListener("click", async () => {
    const reason = String(rationale.value || "").trim();
    if (!reason) {
      error.textContent = "Enter a waiver rationale.";
      rationale.focus();
      return;
    }
    confirm.disabled = true;
    cancel.disabled = true;
    busy = true;
    dialog.setAttribute("aria-busy", "true");
    confirm.textContent = "Waiving…";
    const fail = (message) => {
      confirm.disabled = false;
      cancel.disabled = false;
      busy = false;
      dialog.setAttribute("aria-busy", "false");
      confirm.textContent = "Waive case";
      error.textContent = message;
    };
    let result;
    try {
      result = await callFunction(
        context.client,
        "qa.case.waive",
        { rationale: reason },
        {
          kind: "qa_requirement",
          qa_requirement_id: row.last_result.requirement_id,
        },
      );
    } catch (callError) {
      if (overlay.isConnected === false || !overlay.parentNode) return;
      fail(rejectedCallMessage(callError, "Waiver failed."));
      return;
    }
    if (overlay.isConnected === false || !overlay.parentNode) return;
    if (!result.envelope.success) {
      fail(result.envelope?.error?.message || "Waiver failed.");
      return;
    }
    busy = false;
    close();
    reload();
  });
  actions.appendChild(confirm);
  dialog.appendChild(actions);
  overlay.appendChild(dialog);
  queueMicrotask(() => {
    if (!overlay.parentNode || overlay.isConnected === false) return;
    mountWorkflowDialog({ documentNode, host: overlay, dialog,
      dismiss: close, initialFocus: rationale });
  });
  return overlay;
}
