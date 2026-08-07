import { buildUniverseRoute } from "./universe_navigation.js";
import { callFunction, el, renderError } from "./universe_view_support.js";
import { workflowPanel } from "./workflow_view_primitives.js";

function countNoun(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

// "applies to 3 workflows / all projects" — how far beyond this workflow
// the instruction reaches, so an operator edits it knowing the blast radius.
export function instructionReachHint(instruction) {
  const projectsPart = instruction.applies_to_all_projects
    ? "all projects"
    : countNoun((instruction.project_ids || []).length, "project");
  return "applies to " +
    `${countNoun((instruction.workflow_ids || []).length, "workflow")}` +
    ` / ${projectsPart}`;
}

// The workflow detail's view of the operator-authored execution
// instructions that resolve for it: active instructions naming this
// workflow, each linking into the Execution Instructions view where the
// full roster is edited.
export function workflowInstructionsPanel(documentNode, workflow, client) {
  const { panel, body } = workflowPanel(documentNode, "Execution instructions");
  body.textContent = "loading…";
  callFunction(client, "workflow.execution_instruction.list", {})
    .then((callResult) => {
      body.replaceChildren();
      if (callResult.status !== 200 || !callResult.envelope.success) {
        renderError(body, callResult);
        return;
      }
      const resolved = ((callResult.envelope.result || {}).instructions || [])
        .filter((instruction) => instruction.status === "active" &&
          (instruction.workflow_ids || []).includes(workflow.id));
      if (!resolved.length) {
        body.appendChild(el(
          documentNode, "p", "empty",
          "No active execution instructions apply to this workflow.",
        ));
        return;
      }
      for (const instruction of resolved) {
        const row = el(documentNode, "div", "workflow-instruction-row");
        const link = el(
          documentNode, "a", "row-link workflow-instruction-title",
          instruction.title,
        );
        link.href = buildUniverseRoute("instructions");
        row.appendChild(link);
        row.appendChild(el(
          documentNode, "span", "workflow-instruction-reach",
          instructionReachHint(instruction),
        ));
        body.appendChild(row);
      }
    })
    .catch((failure) => {
      body.replaceChildren();
      renderError(body, {
        status: 0,
        envelope: { success: false, error: { message: String(failure) } },
      });
    });
  return panel;
}
