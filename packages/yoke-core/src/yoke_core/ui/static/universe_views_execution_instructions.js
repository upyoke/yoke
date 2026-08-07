import {
  callFunction,
  el,
  renderError,
  statePill,
} from "./universe_view_support.js";
import {
  button,
  renderWorkflowDialog,
  workflowPanel,
} from "./workflow_view_primitives.js";
import {
  openExecutionInstructionEditor,
} from "./execution_instruction_editor.js";

function countNoun(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

// "3 workflows / All projects" — where an instruction lands, at a glance.
export function instructionScopeSummary(instruction) {
  const workflowsPart = countNoun(
    (instruction.workflow_ids || []).length, "workflow",
  );
  const projectsPart = instruction.applies_to_all_projects
    ? "All projects"
    : countNoun((instruction.project_ids || []).length, "project");
  return `${workflowsPart} / ${projectsPart}`;
}

export function renderExecutionInstructionsView(context, main) {
  const documentNode = context.document;
  const toolbar = el(documentNode, "div", "instruction-toolbar");
  const content = el(documentNode, "div", "instruction-stack");
  const dialogHost = el(documentNode, "div", "workflow-dialog-host");
  main.replaceChildren(toolbar, content, dialogHost);

  let instructions = [];
  let workflows = [];
  // null renders the list; {} the create editor; a row the edit editor.
  let editing = null;

  const mutation = async (functionId, payload) => {
    const callResult = await callFunction(
      context.client, functionId, payload,
    );
    if (callResult.status !== 200 || !callResult.envelope.success) {
      throw new Error(
        callResult.envelope?.error?.message || "Instruction update failed.",
      );
    }
    return callResult.envelope.result || {};
  };
  const closeDialog = () => dialogHost.replaceChildren();

  const save = async (edit) => {
    let instructionId = editing && editing.id;
    const fields = {
      title: edit.title,
      content: edit.content,
      ordering: edit.ordering,
      status: edit.status,
    };
    if (instructionId == null) {
      const created = await mutation(
        "workflow.execution_instruction.create", fields,
      );
      instructionId = created.instruction_id;
    } else {
      await mutation("workflow.execution_instruction.update", {
        instruction_id: instructionId, ...fields,
      });
    }
    await mutation("workflow.execution_instruction.set_scope", {
      instruction_id: instructionId,
      workflow_ids: edit.workflowIds,
      applies_to_all_projects: edit.appliesToAllProjects,
      project_ids: edit.projectIds,
    });
    editing = null;
    await load();
  };

  const openDelete = (instruction) => {
    renderWorkflowDialog(documentNode, dialogHost, {
      title: `Delete “${instruction.title}”?`,
      subtitle:
        "The instruction stops applying everywhere its scope reached.",
      lines: [],
      impact: "Deleting cannot be undone.",
      confirmText: "Delete instruction",
      pendingText: "Deleting…",
      cancel: closeDialog,
      confirm: async () => {
        await mutation("workflow.execution_instruction.delete", {
          instruction_id: instruction.id,
        });
        closeDialog();
        editing = null;
        await load();
      },
    });
  };

  const openEditor = (instruction) => {
    editing = instruction;
    render();
  };

  const instructionRow = (instruction) => {
    const row = button(documentNode, "", "instruction-row");
    row.appendChild(el(
      documentNode, "span", "instruction-row-title", instruction.title,
    ));
    const status = statePill(documentNode, instruction.status);
    if (status) row.appendChild(status);
    // An instruction attached to no workflow matches nothing; say so
    // rather than letting it look configured while silently doing nothing.
    if (!(instruction.workflow_ids || []).length) {
      row.appendChild(el(
        documentNode, "span", "instruction-inert-badge", "inert",
      ));
    }
    row.appendChild(el(
      documentNode, "span", "instruction-row-scope",
      instructionScopeSummary(instruction),
    ));
    row.addEventListener("click", () => openEditor(instruction));
    return row;
  };

  const render = () => {
    toolbar.replaceChildren();
    if (editing !== null) {
      openExecutionInstructionEditor({
        documentNode,
        host: content,
        instruction: editing,
        workflows,
        projects: context.projects(),
        save,
        remove: editing.id != null ? () => openDelete(editing) : null,
        cancel: () => { editing = null; render(); },
      });
      return;
    }
    const create = button(
      documentNode, "New instruction", "workflow-button primary",
    );
    create.addEventListener("click", () => openEditor({}));
    toolbar.appendChild(create);
    const listing = workflowPanel(
      documentNode, "Execution instructions",
      { count: instructions.length },
    );
    if (!instructions.length) {
      listing.body.appendChild(el(
        documentNode, "p", "empty", "No execution instructions yet.",
      ));
    }
    for (const instruction of instructions) {
      listing.body.appendChild(instructionRow(instruction));
    }
    content.replaceChildren(listing.panel);
  };

  const load = async () => {
    let listResult;
    let definitionResult = null;
    try {
      [listResult, definitionResult] = await Promise.all([
        callFunction(
          context.client, "workflow.execution_instruction.list", {},
        ),
        callFunction(context.client, "workflows.definition.get", {}),
      ]);
    } catch (fetchError) {
      listResult = {
        status: 0,
        envelope: { success: false, error: { message: String(fetchError) } },
      };
    }
    if (!context.isMounted()) return;
    if (listResult.status !== 200 || !listResult.envelope.success) {
      const failure = workflowPanel(documentNode, "Execution instructions");
      renderError(failure.body, listResult);
      content.replaceChildren(failure.panel);
      return;
    }
    instructions = (listResult.envelope.result || {}).instructions || [];
    workflows =
      (definitionResult?.envelope?.result || {}).workflows || [];
    render();
  };
  load();
}
