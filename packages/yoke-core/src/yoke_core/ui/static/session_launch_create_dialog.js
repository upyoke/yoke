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
    ...(fields.effort.value
      ? { reasoning_effort: String(fields.effort.value) } : {}),
    ...(fields.context.value
      ? { context_window_tokens: Number(fields.context.value) } : {}),
    allow_surface_fallback: Boolean(fields.fallback.checked),
  };
}

function previewConfirmsSelection(request, result) {
  return [
    ["model", "requested_model"],
    ["reasoning_effort", "requested_reasoning_effort"],
    ["context_window_tokens", "requested_context_window_tokens"],
  ].every(([asked, confirmed]) => (
    String(request[asked] ?? "") === String(result[confirmed] ?? "")
  ));
}

function modelSelectionNotice(request, launchable) {
  if (!launchable) return "";
  const requested = [
    request.model ? `Model ${request.model}` : "",
    request.reasoning_effort
      ? `reasoning effort ${request.reasoning_effort}` : "",
    request.context_window_tokens
      ? `context window ${request.context_window_tokens} tokens` : "",
  ].filter(Boolean);
  if (!requested.length) return "";
  return ` ${requested.join(", ")} will be verified at registration; the requested model selection will be recorded separately, and served facts settle independently.`;
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
    "Choose an exact surface, preview eligible machines, then create. Optional model, effort, and context asks are recorded separately from served facts; Yoke will not silently change the selection or surface.",
  );
  help.id = "session-launch-create-help";
  shell.dialog.appendChild(help);
  const fields = {
    project: el(documentNode, "select", "session-control-input"),
    item: el(documentNode, "input", "session-control-input"),
    surface: el(documentNode, "select", "session-control-input"),
    machine: el(documentNode, "select", "session-control-input"),
    model: el(documentNode, "input", "session-control-input"),
    effort: el(documentNode, "input", "session-control-input"),
    context: el(documentNode, "input", "session-control-input"),
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
  fields.effort.type = "text";
  fields.effort.placeholder = "Optional provider effort level";
  fields.effort.value = "";
  fields.context.type = "number";
  fields.context.min = "1";
  fields.context.step = "1";
  fields.context.placeholder = "Optional token count, for example 1000000";
  fields.context.value = "";
  fields.item.type = "text";
  fields.item.placeholder = "Required work item ref";
  for (const [label, field] of [
    ["Project", fields.project],
    ["Work item", fields.item],
    ["Requested surface", fields.surface],
    ["Allow same-family fallback", fields.fallback],
    ["Machine", fields.machine],
    ["Requested model (verified after launch)", fields.model],
    ["Requested reasoning effort", fields.effort],
    ["Requested context window (tokens)", fields.context],
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
      if (!previewConfirmsSelection(request, result)) {
        status.textContent = "Launch preview did not confirm the requested model selection. Refresh after the control plane is updated.";
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
      const modelNotice = modelSelectionNotice(request, result.launchable);
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
