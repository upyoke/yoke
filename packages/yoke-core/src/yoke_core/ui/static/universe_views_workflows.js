// The workflow registry as an operator experience: select one immutable
// workflow, follow its lifecycle, inspect each entry gate, understand its
// execution posture and mechanics, and read its version history.

import {
  callFunction,
  el,
  renderError,
} from "./universe_view_support.js";
import {
  renderTabs,
  sortedWorkflows,
  workflowPanel,
} from "./workflow_view_primitives.js";
import { renderStages } from "./workflow_view_lifecycle.js";
import {
  renderMechanics,
  renderPosture,
} from "./workflow_view_policy.js";
import { renderVersionHistory } from "./workflow_view_versions.js";

function renderSelectedWorkflow(
  documentNode,
  content,
  intro,
  workflow,
  catalogById,
  stageSelections,
  rerender,
) {
  intro.textContent = workflow.description || "";
  intro.hidden = !workflow.description;
  const stages = workflow.definition?.stages || [];
  const selectedStageId = stageSelections.get(workflow.id) ||
    (stages[0] && stages[0].id);
  content.replaceChildren(
    renderStages(
      documentNode,
      workflow,
      catalogById,
      selectedStageId,
      (stageId) => {
        stageSelections.set(workflow.id, stageId);
        rerender();
      },
    ),
    renderPosture(documentNode, workflow),
    renderMechanics(documentNode, workflow),
    renderVersionHistory(documentNode, workflow),
  );
}

function renderFailure(documentNode, tabs, intro, content, callResult) {
  const failure = workflowPanel(documentNode, "Workflows");
  renderError(failure.body, callResult);
  tabs.replaceChildren();
  intro.hidden = true;
  content.replaceChildren(failure.panel);
}

export function renderWorkflowsView(context, main) {
  const documentNode = context.document;
  const tabs = el(documentNode, "div", "workflow-tabs");
  tabs.setAttribute("role", "tablist");
  const intro = el(documentNode, "p", "workflow-intro");
  const content = el(documentNode, "div", "workflow-stack");
  const loading = workflowPanel(documentNode, "Stages");
  loading.body.textContent = "loading…";
  content.appendChild(loading.panel);
  main.replaceChildren(tabs, intro, content);

  let workflows = [];
  let catalogById = new Map();
  let selectedWorkflowId = null;
  const stageSelections = new Map();

  const render = () => {
    if (!workflows.length) return;
    const selected = workflows.find(
      (workflow) => workflow.id === selectedWorkflowId,
    ) || workflows[0];
    selectedWorkflowId = selected.id;
    renderTabs(
      documentNode,
      tabs,
      workflows,
      selectedWorkflowId,
      (workflowId) => {
        selectedWorkflowId = workflowId;
        render();
      },
    );
    renderSelectedWorkflow(
      documentNode,
      content,
      intro,
      selected,
      catalogById,
      stageSelections,
      render,
    );
  };

  Promise.resolve()
    .then(() => callFunction(
      context.client, "workflows.definition.get", {},
    ))
    .then((callResult) => {
      if (!context.isMounted()) return;
      const ok = callResult.status === 200 && callResult.envelope.success;
      if (!ok) {
        renderFailure(documentNode, tabs, intro, content, callResult);
        return;
      }
      const result = callResult.envelope.result || {};
      workflows = sortedWorkflows(result.workflows || []);
      catalogById = new Map(
        (result.gate_catalog || []).map((gate) => [gate.id, gate]),
      );
      selectedWorkflowId = workflows.some(
        (workflow) => workflow.id === "dash",
      ) ? "dash" : (workflows[0] && workflows[0].id);
      if (!workflows.length) {
        const empty = workflowPanel(documentNode, "Workflows");
        empty.body.appendChild(el(
          documentNode, "p", "empty", "No workflows declared.",
        ));
        tabs.replaceChildren();
        intro.hidden = true;
        content.replaceChildren(empty.panel);
        return;
      }
      render();
    })
    .catch((fetchError) => {
      if (!context.isMounted()) return;
      renderFailure(documentNode, tabs, intro, content, {
        status: 0,
        envelope: {
          success: false,
          error: { message: String(fetchError) },
        },
      });
    });
}
