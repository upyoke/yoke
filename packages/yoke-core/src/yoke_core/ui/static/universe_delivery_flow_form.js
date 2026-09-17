// Authoring a deployment flow definition: create one, revise one, or cut the
// next version of one.
//
// A definition a run has referenced is immutable, and the server is what
// enforces that — these call the same registered functions the CLI does, so
// the screen is a second adapter onto one authority rather than a second
// authority. What the screen adds is the check before the write: a definition
// is validated against the serving runtime, and its verdict has to be read
// before anything is saved. A flow whose stage target the runtime cannot
// execute fails at 2am inside a release, not here.

import { callFunction, el, labelledField, liveStatus } from "./universe_view_support.js";
import { clearWorkflowDialog } from "./workflow_accessibility.js";
import { workflowDialogShell } from "./workflow_dialog_shell.js";

const FIELD_CLASS = "delivery-flow-field";

// The modes differ only in which identity fields are asked for and which
// function the save lands on. Everything else — the configuration, the
// validation, the verdict — is one form.
const MODES = {
  create: {
    title: "New deployment flow",
    confirm: "Create flow",
    identity: "new",
  },
  edit: {
    title: "Edit deployment flow",
    confirm: "Save changes",
    identity: "fixed",
  },
  clone: {
    title: "New version of this flow",
    confirm: "Create version",
    identity: "new",
  },
};

function textField(documentNode, label, value = "", { rows = 0, hint } = {}) {
  const control = rows
    ? el(documentNode, "textarea")
    : el(documentNode, "input");
  if (rows) control.setAttribute("rows", String(rows));
  else control.type = "text";
  control.value = value == null ? "" : String(value);
  const field = labelledField(documentNode, label, control, FIELD_CLASS);
  if (hint) {
    field.appendChild(el(documentNode, "span", "delivery-flow-field-hint", hint));
  }
  return { control, field };
}

function selectField(documentNode, label, choices, value) {
  const control = el(documentNode, "select");
  for (const choice of choices) {
    const option = el(documentNode, "option", null, choice.label);
    option.value = String(choice.id);
    control.appendChild(option);
  }
  // An empty selection is no selection: fall back to the first choice
  // rather than leaving the control on a value that names nothing.
  control.value = String(value || choices[0]?.id || "");
  return { control, field: labelledField(documentNode, label, control, FIELD_CLASS) };
}

// The verdict, in the terms that decide whether this definition can run:
// whether it is valid at all, whether this runtime can execute every stage
// target, and whether each QA stage can prove whose verdict it carries.
function verdictLines(result) {
  const lines = [];
  lines.push(result.valid ? "Definition is valid." : "Definition is not valid.");
  lines.push(result.execution_supported
    ? "Every stage target is executable by the serving runtime."
    : "The serving runtime cannot execute every stage target.");
  if (result.unsupported_target_kinds?.length) {
    lines.push(
      `Unsupported target kinds: ${result.unsupported_target_kinds.join(", ")}.`,
    );
  }
  if (result.unprovable_qa_identity_stages?.length) {
    lines.push(
      "QA stages that cannot prove who ruled on them: "
      + `${result.unprovable_qa_identity_stages.join(", ")}.`,
    );
  }
  lines.push(
    `Definition schema ${result.definition_schema_version} · `
    + `serving schema ${result.serving_schema_version}.`,
  );
  return lines;
}

async function callOrThrow(context, functionId, payload, target) {
  const result = await callFunction(context.client, functionId, payload, target);
  if (result.status !== 200 || !result.envelope?.success) {
    throw new Error(
      result.envelope?.error?.message
      || `${functionId} refused with status ${result.status}`,
    );
  }
  return result.envelope.result || {};
}

function stagesText(flow) {
  const stages = flow?.stages;
  if (typeof stages === "string") return stages;
  return JSON.stringify(stages || [], null, 2);
}

export function openDeliveryFlowForm(context, host, {
  mode = "create", flow = null, projects = [], onSaved = () => {},
} = {}) {
  const documentNode = context.document;
  const spec = MODES[mode] || MODES.create;
  const close = () => clearWorkflowDialog(host);
  const shell = workflowDialogShell(documentNode, host, spec.title, close);
  const form = el(documentNode, "div", "delivery-flow-form");

  const sourceProject = String(flow?.project_id || flow?.project || "");
  const project = selectField(
    documentNode,
    "Project",
    projects.map((row) => ({ id: String(row.id), label: row.slug || row.name })),
    sourceProject,
  );
  const flowId = textField(
    documentNode,
    "Flow id",
    mode === "clone" ? "" : flow?.id || "",
    { hint: "Stable identity. A definition a run has referenced keeps it." },
  );
  const name = textField(documentNode, "Name", flow?.name || "");
  const description = textField(
    documentNode, "Description", flow?.description || "", { rows: 2 },
  );
  const stages = textField(
    documentNode, "Stages", stagesText(flow), {
      rows: 10,
      hint: "The ordered pipeline, as JSON. Every run freezes this.",
    },
  );
  const onFailure = selectField(documentNode, "On failure", [
    { id: "halt", label: "halt — stop the run" },
    { id: "continue", label: "continue — run the remaining stages" },
  ], flow?.on_failure || "halt");
  const targetTier = textField(
    documentNode, "Target tier", flow?.target_tier || "",
  );
  const environment = textField(
    documentNode, "Environment", flow?.target_environment || flow?.environment || "",
  );
  const doneDescription = textField(
    documentNode, "Done description", flow?.done_description || "",
  );
  const status = selectField(documentNode, "Status", [
    { id: "disabled", label: "disabled — assigns to nothing yet" },
    { id: "active", label: "active — available to new runs" },
  ], mode === "edit" ? flow?.status || "disabled" : "disabled");

  // A clone keeps its source's project: the new version supersedes a
  // definition that already belongs to one.
  if (mode !== "create") project.control.disabled = true;
  if (mode === "edit") flowId.control.disabled = true;
  const fields = [project.field, flowId.field, name.field, description.field,
    stages.field, onFailure.field, targetTier.field, environment.field,
    doneDescription.field];
  if (mode !== "edit") fields.push(status.field);
  for (const field of fields) form.appendChild(field);
  shell.dialog.appendChild(form);

  const report = liveStatus(documentNode, "delivery-flow-validation");
  shell.dialog.appendChild(report);
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = el(documentNode, "button", "workflow-button", "Cancel");
  const validate = el(
    documentNode, "button", "workflow-button", "Validate definition",
  );
  const save = el(documentNode, "button", "workflow-button primary", spec.confirm);
  for (const control of [cancel, validate, save]) control.type = "button";
  // Nothing is written until the serving runtime has answered for it.
  save.disabled = true;
  actions.appendChild(cancel);
  actions.appendChild(validate);
  actions.appendChild(save);
  shell.dialog.appendChild(actions);

  const show = (text, tone) => {
    report.className = `delivery-flow-validation ${tone}`.trim();
    report.textContent = text;
    report.hidden = false;
  };
  const invalidate = () => {
    save.disabled = true;
    report.hidden = true;
  };
  for (const control of [stages.control, targetTier.control,
    environment.control, project.control]) {
    control.addEventListener("input", invalidate);
    control.addEventListener("change", invalidate);
  }

  validate.addEventListener("click", async () => {
    validate.disabled = true;
    show("Validating against the serving runtime…", "");
    try {
      const result = await callOrThrow(context, "deployment_flows.validate", {
        project: project.control.value,
        stages: stages.control.value,
        target_tier: targetTier.control.value || null,
        environment: environment.control.value || null,
        status: mode === "edit" ? flow?.status || "disabled" : status.control.value,
      });
      const usable = Boolean(result.valid && result.execution_supported);
      show(verdictLines(result).join(" "), usable ? "is-valid" : "is-invalid");
      save.disabled = !usable;
    } catch (failure) {
      show(String(failure?.message || failure), "is-invalid");
      save.disabled = true;
    } finally {
      validate.disabled = false;
    }
  });

  const changes = () => ({
    name: name.control.value,
    description: description.control.value,
    stages: stages.control.value,
    on_failure: onFailure.control.value,
    target_tier: targetTier.control.value || null,
    environment: environment.control.value || null,
    done_description: doneDescription.control.value || null,
  });
  const submit = async () => {
    if (mode === "edit") {
      return callOrThrow(context, "deployment_flows.update", {
        flow_id: flow.id, changes: changes(),
      });
    }
    if (mode === "clone") {
      return callOrThrow(context, "deployment_flows.version", {
        source_flow_id: flow.id,
        new_flow_id: flowId.control.value,
        name: name.control.value,
        changes: changes(),
        status: status.control.value,
      });
    }
    // Creation is the one call whose project is not implied by an existing
    // definition, so it rides on the target rather than in the payload.
    return callOrThrow(context, "deployment_flows.create", {
      flow_id: flowId.control.value,
      name: name.control.value,
      stages: stages.control.value,
      description: description.control.value,
      on_failure: onFailure.control.value,
      target_tier: targetTier.control.value || null,
      environment: environment.control.value || null,
      done_description: doneDescription.control.value || null,
      status: status.control.value,
    }, { kind: "global", project_id: project.control.value });
  };
  cancel.addEventListener("click", shell.dismiss);
  save.addEventListener("click", async () => {
    save.disabled = true;
    shell.dialog.setAttribute("aria-busy", "true");
    show("Saving…", "");
    try {
      await submit();
      close();
      onSaved();
    } catch (failure) {
      shell.dialog.setAttribute("aria-busy", "false");
      show(String(failure?.message || failure), "is-invalid");
      save.disabled = false;
    }
  });
  shell.activate(mode === "edit" ? name.control : flowId.control);
  return shell;
}
