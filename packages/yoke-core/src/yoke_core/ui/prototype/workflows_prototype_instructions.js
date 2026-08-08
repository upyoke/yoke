// Execution instructions, folded into the workflow they act on. An
// instruction has no title, no ordering and no status: it is its content, the
// workflows it names, and the projects it reaches. Editing happens here, so
// there is no second page to keep in sync.

import { button, checkbox, el, panel } from "./workflows_prototype_dom.js";

// Resolution order is general to specific, then by id — the order an agent
// reads them in, so the list shows that order rather than inventing one.
export function resolveFor(instructions, workflowId) {
  return instructions
    .filter((entry) => entry.applies_to_all_workflows ||
      (entry.workflow_ids || []).includes(workflowId))
    .sort((left, right) =>
      Number(right.applies_to_all_workflows) -
        Number(left.applies_to_all_workflows) ||
      left.id - right.id);
}

function count(value, noun) {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}

// How far past this workflow the instruction reaches, so an edit is made
// knowing its blast radius.
export function reachHint(instruction) {
  const workflows = instruction.applies_to_all_workflows
    ? "all workflows"
    : count((instruction.workflow_ids || []).length, "workflow");
  const projects = instruction.applies_to_all_projects
    ? "all projects"
    : count((instruction.project_ids || []).length, "project");
  return `applies to ${workflows} / ${projects}`;
}

// An instruction bound to no workflow matches nothing. All-workflows can
// never be inert, so the badge asks about the junction rows only.
function isInert(instruction) {
  return !instruction.applies_to_all_workflows &&
    !(instruction.workflow_ids || []).length;
}

function instructionRow(documentNode, instruction, actions) {
  const row = el(documentNode, "div", "wp-instruction-row");
  const head = el(documentNode, "div", "wp-instruction-head");
  head.appendChild(el(documentNode, "span", "wp-instruction-reach",
    reachHint(instruction)));
  if (isInert(instruction)) {
    head.appendChild(el(documentNode, "span", "instruction-inert-badge",
      "inert"));
  }
  const edit = button(documentNode, "Edit", "workflow-button compact");
  edit.addEventListener("click", () => actions.edit(instruction));
  head.appendChild(edit);
  row.appendChild(head);
  // The block renders content and nothing else: what the agent is told is
  // the whole of what the operator wrote.
  row.appendChild(el(documentNode, "p", "wp-instruction-content",
    instruction.content));
  return row;
}

function checkboxGroup(
  documentNode, host, { allLabel, allChecked, members, onAll },
) {
  const group = el(documentNode, "div", "wp-checkbox-group");
  const memberInputs = [];
  const sync = (checked) => {
    for (const input of memberInputs) input.disabled = checked;
    group.classList.toggle("all-selected", checked);
  };
  group.appendChild(checkbox(
    documentNode, allChecked, allLabel, "wp-checkbox-all",
    (event) => { onAll(event.target.checked); sync(event.target.checked); },
  ).row);
  for (const member of members) {
    const entry = checkbox(
      documentNode, member.checked, member.label, "wp-checkbox-member",
      (event) => member.onToggle(event.target.checked),
    );
    memberInputs.push(entry.input);
    group.appendChild(entry.row);
  }
  sync(allChecked);
  host.appendChild(group);
}

function editor(documentNode, host, context) {
  const { instruction, workflows, projects, save, remove, cancel } = context;
  const existing = instruction.id != null;
  const state = {
    content: instruction.content || "",
    allWorkflows: Boolean(instruction.applies_to_all_workflows),
    workflowIds: new Set(instruction.workflow_ids || []),
    allProjects: Boolean(instruction.applies_to_all_projects),
    projectIds: new Set((instruction.project_ids || []).map(Number)),
  };
  const editing = panel(documentNode, existing
    ? "Edit execution instruction" : "New execution instruction");
  editing.panel.classList.add("wp-instruction-editor");

  editing.body.appendChild(el(documentNode, "div", "workflow-field-label",
    "Instruction"));
  const content = el(documentNode, "textarea",
    "workflow-field wp-instruction-input");
  content.value = state.content;
  content.setAttribute("rows", "4");
  content.addEventListener("input", () => { state.content = content.value; });
  editing.body.appendChild(content);

  editing.body.appendChild(el(documentNode, "div", "workflow-field-label",
    "Workflows"));
  checkboxGroup(documentNode, editing.body, {
    allLabel: "All workflows",
    allChecked: state.allWorkflows,
    onAll: (checked) => { state.allWorkflows = checked; },
    members: workflows.map((workflow) => ({
      label: workflow.name,
      checked: state.workflowIds.has(workflow.id),
      onToggle: (checked) => {
        if (checked) state.workflowIds.add(workflow.id);
        else state.workflowIds.delete(workflow.id);
      },
    })),
  });

  editing.body.appendChild(el(documentNode, "div", "workflow-field-label",
    "Projects"));
  checkboxGroup(documentNode, editing.body, {
    allLabel: "All projects",
    allChecked: state.allProjects,
    onAll: (checked) => { state.allProjects = checked; },
    members: projects.map((project) => ({
      label: project.slug,
      checked: state.projectIds.has(Number(project.id)),
      onToggle: (checked) => {
        if (checked) state.projectIds.add(Number(project.id));
        else state.projectIds.delete(Number(project.id));
      },
    })),
  });

  const actions = el(documentNode, "div", "wp-editor-actions");
  const cancelButton = button(documentNode, "Cancel");
  cancelButton.addEventListener("click", cancel);
  actions.appendChild(cancelButton);
  if (remove) {
    const deleteButton = button(documentNode, "Delete",
      "workflow-button wp-delete");
    deleteButton.addEventListener("click", remove);
    actions.appendChild(deleteButton);
  }
  const saveButton = button(documentNode,
    existing ? "Save instruction" : "Create instruction",
    "workflow-button primary");
  saveButton.addEventListener("click", () => save({
    id: instruction.id,
    content: state.content,
    applies_to_all_workflows: state.allWorkflows,
    workflow_ids: [...state.workflowIds],
    applies_to_all_projects: state.allProjects,
    project_ids: [...state.projectIds],
  }));
  actions.appendChild(saveButton);
  editing.body.appendChild(actions);
  host.appendChild(editing.panel);
}

export function renderInstructions(documentNode, workflow, context) {
  const resolved = resolveFor(context.instructions, workflow.id);
  if (context.editing) {
    const host = el(documentNode, "div");
    editor(documentNode, host, {
      instruction: context.editing,
      workflows: context.workflows,
      projects: context.projects,
      save: context.save,
      remove: context.editing.id != null ? context.remove : null,
      cancel: context.cancel,
    });
    return host.children[0];
  }
  const { panel: host, body } = panel(documentNode, "Execution instructions",
    { count: resolved.length });
  body.appendChild(el(documentNode, "p", "wp-panel-note",
    `What every ${workflow.name} item tells its agent, in the order the ` +
    "agent reads it — general instructions first, then the ones that name " +
    "this workflow."));
  if (!resolved.length) {
    body.appendChild(el(documentNode, "p", "empty",
      "No execution instructions apply to this workflow."));
  }
  for (const instruction of resolved) {
    body.appendChild(instructionRow(documentNode, instruction, {
      edit: context.edit,
    }));
  }
  const create = button(documentNode, "New instruction",
    "workflow-button primary wp-new-instruction");
  create.addEventListener("click", () => context.edit({}));
  body.appendChild(create);
  return host;
}
