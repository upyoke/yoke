import {
  callFunction,
  el,
} from "./universe_view_support.js";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

export function isTerminalizable(row) {
  return Boolean(row?.id) && !TERMINAL_STATUSES.has(String(row.status || ""));
}

function rejectedCallMessage(error) {
  if (error instanceof Error && error.message) return error.message;
  return String(error || "Terminalization failed.");
}

export function terminalizationDialog(context, row, onSuccess) {
  const documentNode = context.document;
  const overlay = el(
    documentNode, "div", "deployment-terminalization-overlay",
  );
  const dialog = el(
    documentNode, "section", "deployment-terminalization-dialog",
  );
  const close = () => {
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
  };
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", `Terminalize ${row.id}`);
  overlay.addEventListener("click", close);
  dialog.addEventListener("click", (event) => event.stopPropagation());
  dialog.appendChild(el(
    documentNode, "h2", null, `Terminalize ${row.id}?`,
  ));
  dialog.appendChild(el(
    documentNode,
    "p",
    "deployment-terminalization-state",
    `Current state: ${row.status || "unknown"}`,
  ));
  dialog.appendChild(el(
    documentNode,
    "p",
    "deployment-terminalization-warning",
    "This permanently closes the control-plane run. It does not stop an external job. Confirm that no external execution is active first.",
  ));

  const dispositionLabel = el(documentNode, "label", null, "Final disposition");
  const disposition = el(
    documentNode, "select", "deployment-terminalization-disposition",
  );
  for (const value of ["cancelled", "failed"]) {
    const option = el(documentNode, "option", null, value);
    option.value = value;
    disposition.appendChild(option);
  }
  disposition.value = "cancelled";
  dispositionLabel.appendChild(disposition);
  dialog.appendChild(dispositionLabel);

  const reasonLabel = el(documentNode, "label", null, "Reason");
  const reason = el(
    documentNode, "textarea", "deployment-terminalization-reason",
  );
  reason.placeholder = "Why is this run being closed?";
  reasonLabel.appendChild(reason);
  dialog.appendChild(reasonLabel);
  const error = el(
    documentNode, "p", "deployment-terminalization-error",
  );
  dialog.appendChild(error);

  const actions = el(
    documentNode, "div", "deployment-terminalization-actions",
  );
  const cancel = el(documentNode, "button", "btn", "Keep run open");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  actions.appendChild(cancel);
  const confirm = el(
    documentNode, "button", "btn primary", "Confirm terminalization",
  );
  confirm.type = "button";
  confirm.addEventListener("click", async () => {
    const cleanReason = String(reason.value || "").trim();
    if (!cleanReason) {
      error.textContent = "Enter a reason before confirming.";
      return;
    }
    confirm.disabled = true;
    confirm.textContent = "Terminalizing…";
    const fail = (message) => {
      confirm.disabled = false;
      confirm.textContent = "Confirm terminalization";
      error.textContent = message;
    };
    let result;
    try {
      result = await callFunction(
        context.client,
        "deployment_runs.terminalize",
        { disposition: disposition.value, reason: cleanReason },
        { kind: "workflow_run", workflow_run_id: row.id },
      );
    } catch (callError) {
      fail(rejectedCallMessage(callError));
      return;
    }
    if (!result.envelope.success) {
      fail(result.envelope?.error?.message || "Terminalization refused.");
      return;
    }
    close();
    onSuccess(result.envelope.result);
  });
  actions.appendChild(confirm);
  dialog.appendChild(actions);
  overlay.appendChild(dialog);
  return overlay;
}
