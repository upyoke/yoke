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
  const list = el(documentNode, "ul", "session-launch-eligible");
  for (const relay of relays || []) {
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${relay.machine_id || "unknown machine"} · ${relay.surface || "unknown surface"}`,
    ));
  }
  if (!list.children.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", "No eligible relay."));
  } else host.appendChild(list);
}

export async function openSessionLaunchDialog(context, host, projectRefs, onCreated) {
  const documentNode = context.document;
  const close = () => clearWorkflowDialog(host);
  const shell = workflowDialogShell(documentNode, host, "Create session", close);
  const fields = {
    project: el(documentNode, "select", "session-control-input"),
    surface: el(documentNode, "select", "session-control-input"),
    machine: el(documentNode, "select", "session-control-input"),
    model: el(documentNode, "select", "session-control-input"),
    fallback: el(documentNode, "input", "session-control-checkbox"),
    instructions: el(documentNode, "textarea", "session-control-input session-message-body"),
  };
  fields.fallback.type = "checkbox";
  fields.instructions.setAttribute("rows", "8");
  for (const project of projectRefs) {
    fields.project.appendChild(option(documentNode, project));
  }
  fields.project.value = projectRefs[0] || "";
  fields.machine.appendChild(option(documentNode, "", "Choose automatically"));
  fields.machine.value = "";
  fields.model.appendChild(option(documentNode, "", "Any compatible model"));
  fields.model.value = "";
  for (const [label, field] of [
    ["Project", fields.project],
    ["Requested surface", fields.surface],
    ["Allow same-family fallback", fields.fallback],
    ["Machine", fields.machine],
    ["Exact model (optional)", fields.model],
    ["First operational message", fields.instructions],
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

  const [relayResult, ...sessionResults] = await Promise.all([
    sessionControlCall(context, "session_control.relay.list", { limit: 500 }),
    ...projectRefs.map((project) => sessionControlCall(
      context, "sessions.list", { project, limit: 500 },
    )),
  ]);
  const relays = relayResult.relays || [];
  const surfaces = [...new Set(relays.flatMap(
    (relay) => Object.keys(relay.surface_versions || {}),
  ))].sort();
  for (const surface of surfaces) fields.surface.appendChild(option(documentNode, surface));
  fields.surface.value = surfaces[0] || "";
  const models = [...new Set(sessionResults.flatMap(
    (result) => (result.rows || []).map((row) => String(row.model || "")),
  ).filter(Boolean))].sort();
  for (const model of models) fields.model.appendChild(option(documentNode, model));
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
        `${relay.hostname || relay.machine_id} · ${relay.state}`,
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
    status.hidden = true;
  };
  for (const field of Object.values(fields)) {
    field.addEventListener("input", invalidate);
    field.addEventListener("change", invalidate);
  }
  fields.surface.addEventListener("change", refreshMachines);
  fields.fallback.addEventListener("change", refreshMachines);
  cancel.addEventListener("click", shell.dismiss);
  preview.addEventListener("click", async () => {
    if (!fields.project.value || !fields.surface.value || !fields.instructions.value) {
      status.hidden = false;
      status.textContent = "Choose a project and surface, then add instructions.";
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
      previewed = { request, instructions: String(fields.instructions.value) };
      renderEligible(documentNode, eligible, result.eligible_relays || []);
      status.textContent = result.launchable
        ? (result.fallback_used
          ? `Fallback selected ${result.selected_surface}.`
          : `Requested surface ${result.selected_surface} is eligible.`)
        : `Launch refused: ${result.outcome || "unsupported"}.`;
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
        instructions: previewed.instructions,
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
