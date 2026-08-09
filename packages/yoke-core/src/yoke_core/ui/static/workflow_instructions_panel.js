import { callFunction, el, renderError } from "./universe_view_support.js";
import { openExecutionInstructionEditor } from "./execution_instruction_editor.js";
import { button, workflowPanel } from "./workflow_view_primitives.js";

function countNoun(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** How far beyond this workflow an instruction reaches. */
export function instructionReachHint(instruction) {
  const workflowsPart = instruction.applies_to_all_workflows
    ? "all workflows"
    : countNoun((instruction.workflow_ids || []).length, "workflow");
  const projectsPart = instruction.applies_to_all_projects
    ? "all projects"
    : countNoun((instruction.project_ids || []).length, "project");
  return `applies to ${workflowsPart} / ${projectsPart}`;
}

/** Whether *instruction* is one an item on this workflow would receive. */
export function instructionReaches(instruction, workflowId) {
  return Boolean(instruction.applies_to_all_workflows) ||
    (instruction.workflow_ids || []).includes(workflowId);
}

function firstLine(content) {
  const text = String(content || "").trim();
  const line = text.split("\n", 1)[0];
  return line.length > 90 ? `${line.slice(0, 89)}…` : line;
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

/**
 * The operator-authored instructions that reach this workflow, edited here.
 *
 * Editing lives next to the workflow the instruction acts on rather than on a
 * roster of its own: the scope that decides whether an instruction applies is
 * the same thing the reader came here to understand, so splitting them put the
 * question and the answer on different screens.
 */
export function workflowInstructionsPanel(
  documentNode, workflow, client, context = {},
) {
  const { panel, body } = workflowPanel(
    documentNode, "Execution instructions",
  );
  body.textContent = "loading…";

  const reload = () => {
    body.textContent = "loading…";
    callFunction(client, "workflow.execution_instruction.list", {})
      .then((callResult) => {
        body.replaceChildren();
        if (callResult.status !== 200 || !callResult.envelope.success) {
          renderError(body, callResult);
          return;
        }
        render((callResult.envelope.result || {}).instructions || []);
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
      workflows: context.workflows || [workflow],
      projects: context.projects || [],
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

  const render = (instructions) => {
    const reaching = instructions.filter(
      (instruction) => instructionReaches(instruction, workflow.id),
    );
    if (!reaching.length) {
      body.appendChild(el(
        documentNode, "p", "empty",
        "No execution instructions apply to this workflow.",
      ));
    }
    for (const instruction of reaching) {
      const row = el(documentNode, "div", "workflow-instruction-row");
      const summary = el(documentNode, "div", "workflow-instruction-summary");
      summary.appendChild(el(
        documentNode, "div", "workflow-instruction-content",
        firstLine(instruction.content),
      ));
      summary.appendChild(el(
        documentNode, "span", "workflow-instruction-reach",
        instructionReachHint(instruction),
      ));
      row.appendChild(summary);
      const editButton = button(
        documentNode, "Edit", "workflow-button compact",
      );
      editButton.addEventListener("click", () => edit(instruction));
      row.appendChild(editButton);
      body.appendChild(row);
    }
    const add = button(
      documentNode, "New instruction", "workflow-button compact",
    );
    add.addEventListener("click", () => edit({
      // A new instruction starts scoped to the workflow being viewed, because
      // that is the one the operator is looking at when they ask for it.
      workflow_ids: [workflow.id],
      project_ids: [],
    }));
    body.appendChild(add);
  };

  reload();
  return panel;
}
