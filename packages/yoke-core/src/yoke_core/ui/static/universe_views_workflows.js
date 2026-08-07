import { buildUniverseRoute } from "./universe_navigation.js";
import { callFunction, el, renderError } from "./universe_view_support.js";
import {
  renderTabs,
  renderWorkflowDialog,
  sortedWorkflows,
  workflowPanel,
} from "./workflow_view_primitives.js";
import { renderStages } from "./workflow_view_lifecycle.js";
import { renderMechanics, renderPosture } from "./workflow_view_policy.js";
import { renderVersionHistory } from "./workflow_view_versions.js";
import {
  emptyMechanicsData, loadWorkflowMechanicsData,
} from "./workflow_mechanics_data.js";
import {
  openApprovalEditor,
  openProjectDefaultEditor,
} from "./workflow_mechanics_dialogs.js";
import {
  renderPathClaimsDialog,
  renderPathSurveyDialog,
} from "./workflow_path_posture_dialogs.js";
import { clearWorkflowDialog, linkWorkflowPanel } from "./workflow_accessibility.js";
import { workflowInstructionsPanel } from "./workflow_instructions_panel.js";
function renderSelectedWorkflow(
  documentNode,
  content,
  intro,
  workflow,
  catalogById,
  stageSelections,
  rerender,
  actions,
) {
  linkWorkflowPanel(content, workflow.id);
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
    renderPosture(documentNode, workflow, {
      editPathClaims: actions.editPathClaims
        ? (enabled) => actions.editPathClaims(workflow, enabled)
        : null,
      editPathSurvey: actions.editPathSurvey
        ? (enabled) => actions.editPathSurvey(workflow, enabled)
        : null,
    }),
    renderMechanics(documentNode, workflow, {
      mechanics: actions.mechanics,
      editTesting: actions.editTesting
        ? () => actions.editTesting(workflow)
        : null,
      editApprovals: actions.editApprovals
        ? () => actions.editApprovals(workflow)
        : null,
      editDelivery: actions.editDelivery
        ? () => actions.editDelivery(workflow)
        : null,
    }),
    workflowInstructionsPanel(documentNode, workflow, actions.client),
    renderVersionHistory(documentNode, workflow, {
      client: actions.client,
      makeCurrent: actions.makeCurrent
        ? (version) => actions.makeCurrent(workflow, version)
        : null,
      takeUpdate: actions.takeUpdate,
    }),
  );
}
function renderFailure(documentNode, tabs, intro, content, callResult) {
  const failure = workflowPanel(documentNode, "Workflows");
  renderError(failure.body, callResult);
  tabs.replaceChildren();
  intro.hidden = true;
  content.replaceChildren(failure.panel);
}
function replaceWorkflowRoute(documentNode, context, workflowId) {
  const route = buildUniverseRoute("workflows", null, workflowId);
  const history = documentNode.defaultView?.history;
  if (history && typeof history.replaceState === "function") {
    try {
      history.replaceState(history.state ?? null, "", route);
      return true;
    } catch {
      // A constrained host may deny History writes; hash navigation remains
      // the compatible fallback and the app router will render the route.
    }
  }
  context.navigate(route);
  return false;
}
export function renderWorkflowsView(context, main, _scope, routeWorkflowId) {
  const documentNode = context.document;
  const tabs = el(documentNode, "div", "workflow-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Workflow definitions");
  const intro = el(documentNode, "p", "workflow-intro");
  const content = el(documentNode, "div", "workflow-stack");
  const dialogHost = el(documentNode, "div", "workflow-dialog-host");
  const loading = workflowPanel(documentNode, "Stages");
  loading.body.textContent = "loading…";
  content.appendChild(loading.panel);
  main.replaceChildren(tabs, intro, content, dialogHost);
  let workflows = [];
  let catalogById = new Map();
  let selectedWorkflowId = null;
  let mechanicsData = emptyMechanicsData();
  const stageSelections = new Map();
  let dialog = null;
  const mutation = async (functionId, payload) => {
    const callResult = await callFunction(
      context.client, functionId, payload,
    );
    if (callResult.status !== 200 || !callResult.envelope.success) {
      throw new Error(
        callResult.envelope?.error?.message || "Workflow update failed.",
      );
    }
    return callResult.envelope.result || {};
  };
  const closeDialog = () => { dialog = null; clearWorkflowDialog(dialogHost); };
  const renderPathDialog = (renderer, workflow, enabled) =>
    renderer(
      documentNode, dialogHost, workflow, enabled, closeDialog, mutation, load,
    );
  const openPathClaimsDialog = (workflow, enabled) =>
    renderPathDialog(renderPathClaimsDialog, workflow, enabled);
  const openPathSurveyDialog = (workflow, enabled) =>
    renderPathDialog(renderPathSurveyDialog, workflow, enabled);
  const openCurrentDialog = (workflow, version) => {
    const name = workflow.name || workflow.id;
    dialog = {
      title: `Make ${name} v${version.version} current?`,
      subtitle:
        `New ${name} items will pin v${version.version}. ` +
        `Items already underway stay pinned to v${workflow.current_version}.`,
      lines: [],
      impact:
        "The immutable versions are not changed. This only selects the " +
        "version subsequently created items receive.",
      confirmText: `Make v${version.version} current`,
      cancel: closeDialog,
      confirm: async () => {
        await mutation("workflows.current.set", {
          workflow_id: workflow.id,
          version: Number(version.version),
          expected_current_version: Number(workflow.current_version),
        });
        closeDialog();
        await load();
      },
    };
    renderWorkflowDialog(documentNode, dialogHost, dialog);
  };
  const saveProjectDefault = async (kind, workflow, edit) => {
    const valueKey = kind === "testing" ? "plan_id" : "flow_id";
    const value = kind === "testing"
      ? Number(edit.value) : edit.value;
    await mutation(`workflows.${kind}_default.set`, {
      project: edit.project,
      workflow_id: workflow.id,
      [valueKey]: value,
      apply_to_all: edit.applyToAll,
    });
    closeDialog();
    await load();
  };
  const openTestingDialog = (workflow) => {
    dialog = { kind: "testing" };
    openProjectDefaultEditor({
      documentNode,
      host: dialogHost,
      kind: "testing",
      workflow,
      projects: context.projects(),
      data: mechanicsData,
      close: closeDialog,
      save: (edit) => saveProjectDefault("testing", workflow, edit),
    });
  };
  const openDeliveryDialog = (workflow) => {
    dialog = { kind: "delivery" };
    openProjectDefaultEditor({
      documentNode,
      host: dialogHost,
      kind: "delivery",
      workflow,
      projects: context.projects(),
      data: mechanicsData,
      close: closeDialog,
      save: (edit) => saveProjectDefault("delivery", workflow, edit),
    });
  };
  const openApprovalsDialog = (workflow) => {
    dialog = { kind: "approvals" };
    openApprovalEditor({
      documentNode,
      host: dialogHost,
      workflow,
      data: mechanicsData,
      close: closeDialog,
      save: async (approvalDefaults) => {
        await mutation("workflows.approval_defaults.publish", {
          workflow_id: workflow.id,
          expected_current_version: Number(workflow.current_version),
          approval_defaults: approvalDefaults,
        });
        closeDialog();
        await load();
      },
    });
  };
  // Applying re-reads rather than trusting the client's copy of the merge:
  // the server merges again under the current version it is told to expect,
  // so a definition that moved between preview and apply is refused instead
  // of silently overwritten.
  const takeCanonUpdate = async (workflow) => {
    let applied;
    try {
      applied = await callFunction(
        context.client,
        "workflows.canon_update.apply",
        {
          workflow_id: workflow.id,
          expected_current_version: workflow.current_version,
        },
      );
    } catch (failure) {
      return { error: String(failure) };
    }
    if (applied.status !== 200 || !applied.envelope.success) {
      return {
        error: applied.envelope?.error?.message || "Could not take the update.",
      };
    }
    await load();
    return {};
  };

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
        if (replaceWorkflowRoute(
          documentNode, context, selectedWorkflowId,
        )) render();
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
      {
        client: context.client,
        mechanics: mechanicsData,
        editPathClaims: openPathClaimsDialog,
        editPathSurvey: openPathSurveyDialog,
        editTesting: mechanicsData.editable ? openTestingDialog : null,
        editApprovals: mechanicsData.editable ? openApprovalsDialog : null,
        editDelivery: mechanicsData.editable ? openDeliveryDialog : null,
        makeCurrent: mechanicsData.editable ? openCurrentDialog : null,
        takeUpdate: mechanicsData.editable ? takeCanonUpdate : null,
      },
    );
  };
  const load = async () => {
    let callResult;
    try {
      callResult = await callFunction(
      context.client, "workflows.definition.get", {},
      );
      if (!context.isMounted()) return;
      const ok = callResult.status === 200 && callResult.envelope.success;
      if (!ok) {
        renderFailure(documentNode, tabs, intro, content, callResult);
        return;
      }
      const result = callResult.envelope.result || {};
      workflows = sortedWorkflows(result.workflows || []);
      try {
        mechanicsData = await loadWorkflowMechanicsData(
          context, result.flows || [],
        );
      } catch {
        mechanicsData = emptyMechanicsData();
      }
      if (!context.isMounted()) return;
      catalogById = new Map(
        (result.gate_catalog || []).map((gate) => [gate.id, gate]),
      );
      const linkedWorkflowId = String(routeWorkflowId || "").toLowerCase();
      selectedWorkflowId = workflows.some(
        (workflow) => workflow.id === linkedWorkflowId,
      )
        ? linkedWorkflowId
        : workflows.some((workflow) => workflow.id === "dash")
          ? "dash"
          : (workflows[0] && workflows[0].id);
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
    } catch (fetchError) {
      if (!context.isMounted()) return;
      renderFailure(documentNode, tabs, intro, content, {
        status: 0,
        envelope: {
          success: false,
          error: { message: String(fetchError) },
        },
      });
    }
  };
  load();
}
