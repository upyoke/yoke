import { el } from "./universe_view_support.js";
import { button } from "./workflow_view_primitives.js";

function updateCandidates(workflows) {
  return workflows.filter((workflow) => [
    "update_available",
    "customized_update_available",
  ].includes(workflow.canon_status?.state));
}

export function createWorkflowCanonActions(mutation, refresh) {
  let batchOutcome = null;
  return {
    outcome: () => batchOutcome,
    async setFollow(workflow, follow) {
      await mutation("workflows.canon_follow.set", {
        workflow_id: workflow.id,
        follow,
      });
      await refresh();
    },
    async takeAll(workflows) {
      batchOutcome = await mutation("workflows.canon_update.apply_all", {
        workflows: workflows.map((workflow) => ({
          workflow_id: workflow.id,
          expected_current_version: Number(workflow.current_version),
        })),
      });
      await refresh();
      return batchOutcome;
    },
    async takeUpdate(workflow) {
      try {
        await mutation("workflows.canon_update.apply", {
          workflow_id: workflow.id,
          expected_current_version: Number(workflow.current_version),
        });
        await refresh();
        return {};
      } catch (failure) {
        return { error: String(failure?.message || failure) };
      }
    },
  };
}

function workflowName(workflows, workflowId) {
  const workflow = workflows.find((row) => row.id === workflowId);
  return workflow?.name || workflowId;
}

function renderBatchOutcome(documentNode, workflows, outcome) {
  if (!outcome) return null;
  const report = el(documentNode, "div", "workflow-canon-batch-outcome");
  report.appendChild(el(
    documentNode, "strong", null, "Take-all result",
  ));
  const list = el(documentNode, "ul", "workflow-canon-batch-list");
  for (const applied of outcome.applied || []) {
    list.appendChild(el(
      documentNode,
      "li",
      "workflow-canon-batch-entry applied",
      workflowName(workflows, applied.workflow_id) +
        (applied.version ? " — updated to v" + applied.version + "." : " — updated."),
    ));
  }
  for (const refused of outcome.refused || []) {
    list.appendChild(el(
      documentNode,
      "li",
      "workflow-canon-batch-entry refused",
      workflowName(workflows, refused.workflow_id) +
        " — not updated: " + refused.message,
    ));
  }
  report.appendChild(list);
  return report;
}

function wireAction(control, error, action) {
  control.addEventListener("click", async () => {
    control.disabled = true;
    error.hidden = true;
    try {
      await action();
    } catch (failure) {
      control.disabled = false;
      error.textContent = String(failure?.message || failure);
      error.hidden = false;
    }
  });
}

export function renderCanonControls(
  documentNode,
  workflow,
  workflows,
  actions,
) {
  const host = el(documentNode, "div", "workflow-canon-controls");
  const status = workflow.canon_status || {};
  if (status.state && status.state !== "not_applicable") {
    const follow = status.follow === "manual" ? "manual" : "automatic";
    const row = el(documentNode, "div", "workflow-canon-follow");
    row.appendChild(el(
      documentNode,
      "span",
      "workflow-canon-follow-state",
      "Yoke workflow updates: " + follow,
    ));
    if (actions) {
      const next = follow === "automatic" ? "manual" : "auto";
      const toggle = button(
        documentNode,
        follow === "automatic" ? "Use manual updates" : "Follow updates",
        "workflow-button compact workflow-canon-follow-toggle",
      );
      const error = el(documentNode, "span", "workflow-canon-control-error");
      error.hidden = true;
      wireAction(toggle, error, () => actions.setFollow(workflow, next));
      row.appendChild(toggle);
      row.appendChild(error);
    }
    host.appendChild(row);
    if (status.adopted_from_version != null) {
      host.appendChild(el(
        documentNode,
        "p",
        "workflow-canon-adoption-notice",
        "Updated automatically from Yoke version " +
          status.adopted_from_version + ".",
      ));
    }
  }

  const candidates = updateCandidates(workflows);
  if (actions && candidates.length > 1) {
    const batch = el(documentNode, "div", "workflow-canon-batch");
    const takeAll = button(
      documentNode,
      "Take all updates",
      "workflow-button primary workflow-canon-take-all",
    );
    const error = el(documentNode, "span", "workflow-canon-control-error");
    error.hidden = true;
    wireAction(takeAll, error, () => actions.takeAll(candidates));
    batch.appendChild(takeAll);
    batch.appendChild(el(
      documentNode,
      "span",
      "workflow-canon-batch-summary",
      candidates.length + " workflows have published updates.",
    ));
    batch.appendChild(error);
    host.appendChild(batch);
  }
  const outcome = renderBatchOutcome(
    documentNode, workflows, actions?.outcome(),
  );
  if (outcome) host.appendChild(outcome);
  return host.children.length ? host : null;
}
