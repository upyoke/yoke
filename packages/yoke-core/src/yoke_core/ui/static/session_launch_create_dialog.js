import { el } from "./universe_view_support.js";
import { clearWorkflowDialog } from "./workflow_accessibility.js";
import { workflowDialogShell } from "./workflow_dialog_shell.js";
import {
  labelledControl,
  presentSessionControlFailure,
  sessionControlCall,
  sessionControlIdempotencyKey,
  statusRegion,
} from "./universe_session_control_data.js";

function option(documentNode, value, label = value) {
  const node = el(documentNode, "option", null, label);
  node.value = value;
  return node;
}

function payload(fields) {
  return {
    project: String(fields.project.value),
    executor_surface: String(fields.surface.value),
    ...(fields.machine.value ? { machine_id: String(fields.machine.value) } : {}),
    ...(fields.model.value ? { model: String(fields.model.value) } : {}),
    allow_surface_fallback: Boolean(fields.fallback.checked),
  };
}

function surfaceFamily(surface) {
  return String(surface || "").split("-", 1)[0];
}

function renderEligible(documentNode, host, relays) {
  host.replaceChildren();
  if ((relays || []).length) {
    host.appendChild(el(
      documentNode,
      "p",
      "session-control-preview-heading",
      `Eligible machines (${relays.length})`,
    ));
  }
  const list = el(documentNode, "ul", "session-launch-eligible");
  for (const relay of relays || []) {
    list.appendChild(el(
      documentNode,
      "li",
      null,
      [
        relay.hostname
          ? `${relay.hostname} · ${relay.machine_id || "unknown id"}`
          : (relay.machine_id || "unknown machine"),
        relay.surface || "unknown surface",
        relay.liveness || relay.state,
      ].filter(Boolean).join(" · "),
    ));
  }
  if (!list.children.length) {
    host.appendChild(el(
      documentNode,
      "p",
      "sessions-empty",
      "No connected machine supports this surface.",
    ));
  } else host.appendChild(list);
}

export async function openSessionLaunchDialog(context, host, projectRefs, onCreated) {
  const documentNode = context.document;
  const close = () => clearWorkflowDialog(host);
  const shell = workflowDialogShell(documentNode, host, "Create session", close);
  const help = el(
    documentNode,
    "p",
    "session-control-help",
    "Choose an exact surface, preview eligible machines, then create. An optional model is verified only when the new session registers; Yoke will not silently switch surfaces.",
  );
  help.id = "session-launch-create-help";
  shell.dialog.appendChild(help);
  const fields = {
    project: el(documentNode, "select", "session-control-input"),
    item: el(documentNode, "input", "session-control-input"),
    surface: el(documentNode, "select", "session-control-input"),
    machine: el(documentNode, "select", "session-control-input"),
    model: el(documentNode, "input", "session-control-input"),
    fallback: el(documentNode, "input", "session-control-checkbox"),
    raw: el(documentNode, "input", "session-control-checkbox"),
    instructions: el(documentNode, "textarea", "session-control-input session-message-body"),
  };
  fields.fallback.type = "checkbox";
  fields.raw.type = "checkbox";
  fields.instructions.setAttribute("rows", "8");
  fields.instructions.placeholder = "Optional extras appended after the composed mandate";
  fields.instructions.setAttribute("aria-describedby", help.id);
  for (const project of projectRefs) {
    fields.project.appendChild(option(documentNode, project));
  }
  fields.project.value = projectRefs[0] || "";
  fields.machine.appendChild(option(documentNode, "", "Choose automatically"));
  fields.machine.value = "";
  fields.model.type = "text";
  fields.model.placeholder = "Optional provider model ID";
  fields.model.value = "";
  fields.item.type = "text";
  fields.item.placeholder = "Required work item ref";
  for (const [label, field] of [
    ["Project", fields.project],
    ["Work item", fields.item],
    ["Requested surface", fields.surface],
    ["Allow same-family fallback", fields.fallback],
    ["Machine", fields.machine],
    ["Requested model (verified after launch)", fields.model],
    ["Use typed text as the full instruction body", fields.raw],
    ["Optional extras after the composed mandate", fields.instructions],
  ]) shell.dialog.appendChild(labelledControl(documentNode, label, field));

  const status = statusRegion(documentNode);
  const eligible = el(documentNode, "div", "session-launch-preview");
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = el(documentNode, "button", "workflow-button", "Cancel");
  const preview = el(documentNode, "button", "workflow-button", "Preview launch");
  const create = el(documentNode, "button", "workflow-button primary", "Create session");
  for (const button of [cancel, preview, create]) {
    button.type = "button";
    actions.appendChild(button);
  }
  create.disabled = true;
  shell.dialog.appendChild(status);
  shell.dialog.appendChild(eligible);
  shell.dialog.appendChild(actions);
  status.hidden = false;
  status.textContent = "Loading available launch surfaces…";

  const relayResult = await sessionControlCall(
    context, "session_control.relay.list", { limit: 500 },
  );
  const relays = relayResult.relays || [];
  const surfaces = [...new Set(relays.flatMap(
    (relay) => Object.keys(relay.surface_versions || {}),
  ))].sort();
  for (const surface of surfaces) fields.surface.appendChild(option(documentNode, surface));
  fields.surface.value = surfaces[0] || "";
  const noSurfaces = surfaces.length === 0;
  fields.surface.disabled = noSurfaces;
  preview.disabled = noSurfaces;
  status.hidden = !noSurfaces;
  status.textContent = noSurfaces
    ? "No connected relay advertises a launch surface. Reconnect a machine relay before creating a session."
    : "";
  const refreshMachines = () => {
    fields.machine.replaceChildren(option(
      documentNode, "", "Choose automatically",
    ));
    for (const relay of relays.filter((candidate) => {
      const offered = Object.keys(candidate.surface_versions || {});
      if (offered.includes(fields.surface.value)) return true;
      return fields.fallback.checked && offered.some(
        (surface) => surfaceFamily(surface) === surfaceFamily(fields.surface.value),
      );
    })) {
      fields.machine.appendChild(option(
        documentNode,
        String(relay.machine_id),
        `${relay.hostname || relay.machine_id} · ${relay.liveness || relay.state || "unknown"}`,
      ));
    }
    fields.machine.value = "";
  }
  refreshMachines();

  let previewed = null;
  const idempotencyKey = sessionControlIdempotencyKey("workbench-launch");
  const invalidate = () => {
    previewed = null;
    create.disabled = true;
    eligible.replaceChildren();
    status.hidden = !noSurfaces;
    status.textContent = noSurfaces
      ? "No connected relay advertises a launch surface. Reconnect a machine relay before creating a session."
      : "";
  };
  for (const field of Object.values(fields)) {
    field.addEventListener("input", invalidate);
    field.addEventListener("change", invalidate);
  }
  fields.surface.addEventListener("change", refreshMachines);
  fields.fallback.addEventListener("change", refreshMachines);
  cancel.addEventListener("click", shell.dismiss);
  preview.addEventListener("click", async () => {
    if (
      !fields.project.value || !fields.item.value.trim()
      || !fields.surface.value
      || (fields.raw.checked && !fields.instructions.value.trim())
    ) {
      status.hidden = false;
      status.textContent = fields.raw.checked
        ? "Choose a project, work item, and surface, then add the full instruction body."
        : "Choose a project, work item, and surface.";
      return;
    }
    preview.disabled = true;
    status.hidden = false;
    status.textContent = fields.fallback.checked
      ? "Checking requested and same-family surface eligibility…"
      : "Checking requested surface eligibility…";
    try {
      const request = payload(fields);
      const result = await sessionControlCall(
        context, "session_control.launch.preview", request,
      );
      if (String(result.requested_model || "") !== String(request.model || "")) {
        status.textContent = "Launch preview did not confirm the requested model. Refresh after the control plane is updated.";
        create.disabled = true;
        return;
      }
      previewed = {
        request,
        item: String(fields.item.value).trim(),
        instructions: String(fields.instructions.value),
        composeMandate: !fields.raw.checked,
      };
      renderEligible(documentNode, eligible, result.eligible_relays || []);
      const outcome = result.launchable
        ? (result.fallback_used
          ? `Fallback selected ${result.selected_surface}.`
          : `Requested surface ${result.selected_surface} is eligible.`)
        : `Launch refused: ${result.outcome || "unsupported"}.`;
      const modelNotice = request.model && result.launchable
        ? ` Model ${request.model} will be verified when the new session registers.`
        : "";
      status.textContent = `${outcome}${modelNotice}`;
      create.disabled = !result.launchable;
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "Launch eligibility could not be checked.",
      );
    } finally {
      preview.disabled = false;
    }
  });
  create.addEventListener("click", async () => {
    if (!previewed) return;
    create.disabled = true;
    status.hidden = false;
    status.textContent = "Creating the session request…";
    try {
      const result = await sessionControlCall(context, "session_control.launch.create", {
        ...previewed.request,
        item: previewed.item,
        instructions: previewed.instructions,
        compose_mandate: previewed.composeMandate,
        idempotency_key: idempotencyKey,
      });
      close();
      onCreated(result);
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The session request could not be created.",
      );
      create.disabled = false;
    }
  });
  shell.activate(fields.project);
}
