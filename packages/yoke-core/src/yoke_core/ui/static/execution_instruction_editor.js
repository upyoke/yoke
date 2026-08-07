import { el } from "./universe_view_support.js";
import { button, workflowPanel } from "./workflow_view_primitives.js";

function fieldLabel(documentNode, text) {
  return el(documentNode, "div", "workflow-field-label", text);
}

// A labelled checkbox that hands back its input, so the all-projects rule
// can disable members while their checked state stays visible unchanged.
function checkboxRow(documentNode, checked, label, className, toggle) {
  const row = el(
    documentNode, "label",
    ["workflow-checkbox", className].filter(Boolean).join(" "),
  );
  const input = el(documentNode, "input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", toggle);
  row.appendChild(input);
  row.appendChild(el(documentNode, "span", null, label));
  return { row, input };
}

function textField(documentNode, tag, className, value, apply) {
  const input = el(documentNode, tag, `workflow-field ${className}`);
  input.value = String(value ?? "");
  input.addEventListener("input", () => apply(input.value));
  return input;
}

export function openExecutionInstructionEditor({
  documentNode, host, instruction, workflows, projects, save, remove, cancel,
}) {
  const existing = instruction.id != null;
  const state = {
    title: instruction.title || "",
    content: instruction.content || "",
    ordering: instruction.ordering ?? 0,
    active: (instruction.status || "active") === "active",
    workflowIds: new Set(instruction.workflow_ids || []),
    appliesToAllProjects: Boolean(instruction.applies_to_all_projects),
    projectIds: new Set((instruction.project_ids || []).map(Number)),
  };
  const { panel, body } = workflowPanel(
    documentNode,
    existing ? `Edit instruction — ${instruction.title}` : "New instruction",
  );
  panel.classList.add("instruction-editor");

  body.appendChild(fieldLabel(documentNode, "Title"));
  const title = textField(
    documentNode, "input", "instruction-title-input", state.title,
    (value) => { state.title = value; },
  );
  title.type = "text";
  body.appendChild(title);

  body.appendChild(fieldLabel(documentNode, "Content"));
  body.appendChild(textField(
    documentNode, "textarea", "instruction-content-input", state.content,
    (value) => { state.content = value; },
  ));

  body.appendChild(fieldLabel(documentNode, "Ordering"));
  const ordering = textField(
    documentNode, "input", "instruction-ordering-input", state.ordering,
    (value) => { state.ordering = value; },
  );
  ordering.type = "number";
  body.appendChild(ordering);

  body.appendChild(checkboxRow(
    documentNode, state.active, "Active", "instruction-status-toggle",
    (event) => { state.active = event.target.checked; },
  ).row);

  body.appendChild(fieldLabel(documentNode, "Workflows"));
  const workflowGroup = el(
    documentNode, "div", "instruction-checkbox-group instruction-workflows",
  );
  for (const workflow of workflows) {
    workflowGroup.appendChild(checkboxRow(
      documentNode,
      state.workflowIds.has(workflow.id),
      workflow.name || workflow.id,
      "instruction-workflow-checkbox",
      (event) => {
        if (event.target.checked) state.workflowIds.add(workflow.id);
        else state.workflowIds.delete(workflow.id);
      },
    ).row);
  }
  if (!workflows.length) {
    workflowGroup.appendChild(el(
      documentNode, "p", "workflow-field-help", "No workflows declared.",
    ));
  }
  body.appendChild(workflowGroup);

  body.appendChild(fieldLabel(documentNode, "Projects"));
  const projectGroup = el(
    documentNode, "div", "instruction-checkbox-group instruction-projects",
  );
  const projectInputs = [];
  const syncProjectInputs = () => {
    for (const input of projectInputs) {
      input.disabled = state.appliesToAllProjects;
    }
  };
  projectGroup.appendChild(checkboxRow(
    documentNode,
    state.appliesToAllProjects,
    "All projects",
    "instruction-all-projects",
    (event) => {
      state.appliesToAllProjects = event.target.checked;
      syncProjectInputs();
    },
  ).row);
  for (const project of projects) {
    const projectId = Number(project.id);
    const member = checkboxRow(
      documentNode,
      state.projectIds.has(projectId),
      project.slug || project.name || String(projectId),
      "instruction-project-checkbox",
      (event) => {
        if (event.target.checked) state.projectIds.add(projectId);
        else state.projectIds.delete(projectId);
      },
    );
    projectInputs.push(member.input);
    projectGroup.appendChild(member.row);
  }
  syncProjectInputs();
  body.appendChild(projectGroup);

  const error = el(documentNode, "p", "instruction-editor-error");
  error.hidden = true;
  error.setAttribute("role", "alert");
  body.appendChild(error);

  const actions = el(documentNode, "div", "instruction-editor-actions");
  const cancelButton = button(documentNode, "Cancel");
  cancelButton.addEventListener("click", cancel);
  actions.appendChild(cancelButton);
  let deleteButton = null;
  if (remove) {
    deleteButton = button(
      documentNode, "Delete", "workflow-button instruction-delete",
    );
    deleteButton.addEventListener("click", remove);
    actions.appendChild(deleteButton);
  }
  const saveButton = button(
    documentNode,
    existing ? "Save instruction" : "Create instruction",
    "workflow-button primary",
  );
  saveButton.addEventListener("click", async () => {
    const buttons = [cancelButton, deleteButton, saveButton].filter(Boolean);
    for (const node of buttons) node.disabled = true;
    saveButton.textContent = "Saving…";
    error.hidden = true;
    try {
      await save({
        title: state.title,
        content: state.content,
        ordering: Number(state.ordering) || 0,
        status: state.active ? "active" : "disabled",
        workflowIds: [...state.workflowIds],
        appliesToAllProjects: state.appliesToAllProjects,
        projectIds: [...state.projectIds],
      });
    } catch (failure) {
      for (const node of buttons) node.disabled = false;
      saveButton.textContent = existing
        ? "Save instruction" : "Create instruction";
      error.textContent = String(failure?.message || failure);
      error.hidden = false;
    }
  });
  actions.appendChild(saveButton);
  body.appendChild(actions);

  host.replaceChildren(panel);
}
