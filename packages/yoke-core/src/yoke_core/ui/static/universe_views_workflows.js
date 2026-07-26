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
  renderWorkflowDialog,
  sortedWorkflows,
  workflowPanel,
} from "./workflow_view_primitives.js";
import { renderStages } from "./workflow_view_lifecycle.js";
import {
  renderMechanics,
  renderPosture,
} from "./workflow_view_policy.js";
import { renderVersionHistory } from "./workflow_view_versions.js";
import {
  emptyMechanicsData,
  loadWorkflowMechanicsData,
} from "./workflow_mechanics_data.js";
import {
  openApprovalEditor,
  openProjectDefaultEditor,
} from "./workflow_mechanics_dialogs.js";

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
    renderVersionHistory(documentNode, workflow, {
      client: actions.client,
      makeCurrent: actions.makeCurrent
        ? (version) => actions.makeCurrent(workflow, version)
        : null,
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

export function renderWorkflowsView(context, main) {
  const documentNode = context.document;
  const tabs = el(documentNode, "div", "workflow-tabs");
  tabs.setAttribute("role", "tablist");
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

  const closeDialog = () => {
    dialog = null;
    dialogHost.replaceChildren();
  };

  const openPathClaimsDialog = (workflow, enabled) => {
    const nextVersion = Number(workflow.current_version) + 1;
    const name = workflow.name || workflow.id;
    dialog = {
      title: `${enabled ? "Turn on" : "Turn off"} path claims`,
      subtitle: enabled
        ? `Enable path claims for new ${name} items.`
        : `Return new ${name} items to claim-less by default.`,
      lines: [
        {
          title: "What this does",
          description:
            `reserves the files a ${name} will touch, so overlapping work ` +
            "serializes through the claim machinery instead of colliding at merge.",
        },
        {
          title: "Default (off)",
          description:
            `the ${name} executor surveys anticipated conflicts, works in an ` +
            "isolated worktree, and re-checks at merge without registering every path.",
        },
        {
          title: "Turn on when",
          description:
            `${name} items collide often enough that claim coordination costs less ` +
            "than resolving conflicts.",
        },
      ],
      impact:
        `Publishing creates ${name} v${nextVersion}. Items already underway ` +
        `stay pinned to v${workflow.current_version} and are unaffected.`,
      confirmText: `${enabled ? "Turn on" : "Turn off"} path claims`,
      cancel: closeDialog,
      confirm: async () => {
        await mutation("workflows.policy_defaults.publish", {
          workflow_id: workflow.id,
          expected_current_version: Number(workflow.current_version),
          path_claims_default: enabled,
        });
        closeDialog();
        await load();
      },
    };
    renderWorkflowDialog(documentNode, dialogHost, dialog);
  };

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
      {
        client: context.client,
        mechanics: mechanicsData,
        editPathClaims: mechanicsData.editable
          ? openPathClaimsDialog : null,
        editTesting: mechanicsData.editable ? openTestingDialog : null,
        editApprovals: mechanicsData.editable ? openApprovalsDialog : null,
        editDelivery: mechanicsData.editable ? openDeliveryDialog : null,
        makeCurrent: mechanicsData.editable ? openCurrentDialog : null,
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
      mechanicsData = await loadWorkflowMechanicsData(
        context, result.flows || [],
      );
      if (!context.isMounted()) return;
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
