import { callFunction, el, renderError } from "./universe_view_support.js";
import { openExecutionInstructionEditor } from "./execution_instruction_editor.js";
import { button, workflowPanel } from "./workflow_view_primitives.js";

function countNoun(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function roster(value) {
  return typeof value === "function" ? value() : (value || []);
}

/** How far an instruction reaches, independent of the tab in view. */
export function instructionReachHint(instruction) {
  const workflowsPart = instruction.applies_to_all_workflows
    ? "all workflows"
    : countNoun((instruction.workflow_ids || []).length, "workflow");
  const projectsPart = instruction.applies_to_all_projects
    ? "all projects"
    : countNoun((instruction.project_ids || []).length, "project");
  return `applies to ${workflowsPart} / ${projectsPart}`;
}

/** Whether *instruction* would reach an item on this workflow. */
export function instructionReaches(instruction, workflowId) {
  if (workflowId == null || workflowId === "") return true;
  return Boolean(instruction.applies_to_all_workflows) ||
    (instruction.workflow_ids || []).includes(workflowId);
}

function instructionReachesProject(instruction, projectId) {
  if (projectId == null || projectId === "") return true;
  return Boolean(instruction.applies_to_all_projects) ||
    (instruction.project_ids || []).map(Number).includes(Number(projectId));
}

function previewText(content) {
  const text = String(content || "").trim();
  const line = text.split("\n", 1)[0];
  return line.length > 90 ? `${line.slice(0, 89)}…` : line;
}

function bodyNeedsExpand(content) {
  return String(content || "").trim() !== previewText(content);
}

async function call(client, functionId, payload) {
  const result = await callFunction(client, functionId, payload);
  if (result.status !== 200 || !result.envelope.success) {
    throw new Error(
      result.envelope?.error?.message || `${functionId} failed`,
    );
  }
  return result.envelope.result || {};
}

/**
 * Save one instruction's prose and scope, creating it first when new.
 *
 * Content and scope are two functions because they are two different
 * decisions with different authority; an editor that changed both presents
 * them as one action, so both calls land before the caller reloads.
 */
async function persist(client, instruction, draft) {
  const id = instruction.id != null
    ? instruction.id
    : (await call(client, "workflow.execution_instruction.create", {
      content: draft.content,
    })).instruction_id;
  if (instruction.id != null) {
    await call(client, "workflow.execution_instruction.update", {
      instruction_id: id,
      content: draft.content,
    });
  }
  await call(client, "workflow.execution_instruction.set_scope", {
    instruction_id: id,
    applies_to_all_workflows: draft.appliesToAllWorkflows,
    workflow_ids: draft.workflowIds,
    applies_to_all_projects: draft.appliesToAllProjects,
    project_ids: draft.projectIds,
  });
}

function addFilter(documentNode, host, className, label, value, options, apply) {
  const select = el(documentNode, "select", className);
  select.setAttribute("aria-label", label);
  for (const option of options) {
    const node = el(documentNode, "option", null, option.label);
    node.value = option.value;
    if (option.value === value) node.selected = true;
    select.appendChild(node);
  }
  select.value = value;
  select.addEventListener("change", () => apply(select.value));
  host.appendChild(select);
}

/**
 * Page-level roster of operator-authored instructions.
 *
 * Scope lives on each instruction. The selected workflow tab does not own
 * this list, hide rows, or assign scope to a newly created instruction.
 */
export function workflowInstructionsPanel(documentNode, client, context = {}) {
  const { panel, body } = workflowPanel(
    documentNode, "Execution instructions",
  );
  body.textContent = "loading…";
  const expandedIds = new Set();
  let workflowFilter = "";
  let projectFilter = "";
  let listed = [];
  const workflows = () => roster(context.workflows);
  const projects = () => roster(context.projects);

  const reload = () => {
    body.textContent = "loading…";
    callFunction(client, "workflow.execution_instruction.list", {})
      .then((callResult) => {
        body.replaceChildren();
        if (callResult.status !== 200 || !callResult.envelope.success) {
          renderError(body, callResult);
          return;
        }
        paint((callResult.envelope.result || {}).instructions || []);
      })
      .catch((failure) => {
        body.replaceChildren();
        renderError(body, {
          status: 0,
          envelope: {
            success: false, error: { message: String(failure) },
          },
        });
      });
  };

  const edit = (instruction) => {
    const host = el(documentNode, "div", "workflow-instruction-editor-host");
    body.replaceChildren(host);
    openExecutionInstructionEditor({
      documentNode,
      host,
      instruction,
      workflows: workflows(),
      projects: projects(),
      save: async (draft) => {
        await persist(client, instruction, draft);
        reload();
      },
      remove: instruction.id == null ? null : async () => {
        await call(client, "workflow.execution_instruction.delete", {
          instruction_id: instruction.id,
        });
        reload();
      },
      cancel: reload,
    });
  };

  const paint = (instructions) => {
    listed = instructions;
    body.replaceChildren();
    const filters = el(documentNode, "div", "workflow-instruction-filters");
    addFilter(
      documentNode, filters, "workflow-instruction-workflow-filter",
      "Filter by workflow", workflowFilter,
      [
        { value: "", label: "All workflows" },
        ...workflows().map((row) => ({
          value: row.id, label: row.name || row.id,
        })),
      ],
      (value) => { workflowFilter = value; paint(listed); },
    );
    addFilter(
      documentNode, filters, "workflow-instruction-project-filter",
      "Filter by project", projectFilter,
      [
        { value: "", label: "All projects" },
        ...projects().map((row) => ({
          value: String(row.id),
          label: row.slug || row.name || String(row.id),
        })),
      ],
      (value) => { projectFilter = value; paint(listed); },
    );
    body.appendChild(filters);

    const reaching = instructions.filter(
      (row) => instructionReaches(row, workflowFilter) &&
        instructionReachesProject(row, projectFilter),
    );
    const list = el(documentNode, "div", "workflow-instructions-list");
    if (!reaching.length) {
      list.appendChild(el(
        documentNode, "p", "empty",
        instructions.length
          ? "No execution instructions match this filter."
          : "No execution instructions.",
      ));
    }
    for (const instruction of reaching) list.appendChild(renderRow(instruction));
    body.appendChild(list);
    const add = button(
      documentNode, "New instruction",
      "workflow-button compact workflow-instructions-new",
    );
    add.addEventListener("click", () => edit({
      workflow_ids: [],
      project_ids: [],
    }));
    body.appendChild(add);
  };

  const renderRow = (instruction) => {
    const row = el(documentNode, "div", "workflow-instruction-row");
    const summary = el(documentNode, "div", "workflow-instruction-summary");
    const expanded = expandedIds.has(instruction.id);
    const preview = el(
      documentNode, "div",
      expanded ? "workflow-instruction-body" : "workflow-instruction-content",
      expanded
        ? String(instruction.content || "")
        : previewText(instruction.content),
    );
    if (instruction.id != null) {
      preview.id = `instruction-body-${instruction.id}`;
      preview.setAttribute("id", preview.id);
    }
    summary.appendChild(preview);
    summary.appendChild(el(
      documentNode, "span", "workflow-instruction-reach",
      instructionReachHint(instruction),
    ));
    row.appendChild(summary);
    const actions = el(documentNode, "div", "workflow-instruction-actions");
    if (bodyNeedsExpand(instruction.content)) {
      const toggle = button(
        documentNode,
        expanded ? "Show less" : "Show more",
        "workflow-button compact workflow-instruction-expand",
      );
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      if (preview.id) toggle.setAttribute("aria-controls", preview.id);
      toggle.addEventListener("click", () => {
        if (expanded) expandedIds.delete(instruction.id);
        else expandedIds.add(instruction.id);
        paint(listed);
      });
      actions.appendChild(toggle);
    }
    const editButton = button(
      documentNode, "Edit", "workflow-button compact",
    );
    editButton.addEventListener("click", () => edit(instruction));
    actions.appendChild(editButton);
    row.appendChild(actions);
    return row;
  };

  reload();
  return panel;
}
