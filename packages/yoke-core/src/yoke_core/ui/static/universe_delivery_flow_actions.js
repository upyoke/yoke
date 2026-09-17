// What an operator can do to a deployment flow definition from the catalog:
// author a new one, revise the selected one, cut its next version, or take it
// out of service.
//
// Disabling is the only destructive-shaped action here and it destroys
// nothing: a definition a run has referenced is immutable, so retiring one
// means it assigns to nothing new while every run that already froze it keeps
// reading the same definition. The button says that rather than implying a
// delete.

import { callFunction, el } from "./universe_view_support.js";
import { openDeliveryFlowForm } from "./universe_delivery_flow_form.js";

function actionButton(documentNode, label, className = "") {
  const control = el(
    documentNode, "button", `delivery-flow-action ${className}`.trim(), label,
  );
  control.type = "button";
  return control;
}

async function setStatus(context, flow, status) {
  const result = await callFunction(
    context.client, "deployment_flows.set_status",
    { flow_id: flow.id, status },
  );
  if (result.status !== 200 || !result.envelope?.success) {
    throw new Error(
      result.envelope?.error?.message
      || `deployment_flows.set_status refused with status ${result.status}`,
    );
  }
}

export function flowActionsRow({
  documentNode, context, dialogHost, reload, report,
}) {
  const row = el(documentNode, "div", "delivery-flow-actions");
  const create = actionButton(documentNode, "New flow", "primary");
  const edit = actionButton(documentNode, "Edit");
  const clone = actionButton(documentNode, "New version");
  const status = actionButton(documentNode, "Disable");
  for (const control of [create, edit, clone, status]) row.appendChild(control);

  const open = (mode, flow) => openDeliveryFlowForm(context, dialogHost, {
    mode,
    flow,
    projects: context.projects(),
    onSaved: reload,
  });
  let selected = null;
  create.addEventListener("click", () => open("create", null));
  edit.addEventListener("click", () => selected && open("edit", selected));
  clone.addEventListener("click", () => selected && open("clone", selected));
  status.addEventListener("click", async () => {
    if (!selected) return;
    const next = String(selected.status || "").toLowerCase() === "disabled"
      ? "active" : "disabled";
    status.disabled = true;
    report(`${next === "active" ? "Enabling" : "Disabling"} ${selected.name || selected.id}…`, "");
    try {
      await setStatus(context, selected, next);
      reload();
    } catch (failure) {
      report(String(failure?.message || failure), "is-invalid");
      status.disabled = false;
    }
  });

  return {
    row,
    // The action row answers for whichever definition the catalog has open,
    // so it is repainted with the selection rather than rebuilt.
    setSelected(flow) {
      selected = flow;
      const disabled = String(flow?.status || "").toLowerCase() === "disabled";
      edit.disabled = !flow;
      clone.disabled = !flow;
      status.disabled = !flow;
      status.textContent = disabled ? "Enable" : "Disable";
      status.setAttribute("title", disabled
        ? "Make this definition available to new runs again."
        : "Stop assigning new runs to this definition. Runs that already "
          + "froze it are unaffected.");
    },
  };
}
