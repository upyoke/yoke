import { callFunction } from "./universe_view_support.js";

const ROLE_LABELS = {
  owner: "project owner",
  operator: "project operator",
  admin: "org admin",
};

function rows(result) {
  return result.status === 200 && result.envelope.success
    ? (result.envelope.result?.rows || [])
    : [];
}

export function emptyMechanicsData() {
  return {
    testingDefaults: [],
    deliveryDefaults: [],
    approvers: [],
    plansByProject: {},
    flows: [],
    editable: false,
  };
}

export async function loadWorkflowMechanicsData(context, flows = []) {
  const projects = context.projects();
  const mechanicsPromise = callFunction(
    context.client, "workflows.mechanics.get", {},
  );
  const planPromises = projects.map(async (project) => {
    const key = String(project.slug || project.id);
    const result = await callFunction(
      context.client, "qa.plan.list", { project: key },
    );
    return [key, rows(result)];
  });
  const [mechanicsResult, planEntries] = await Promise.all([
    mechanicsPromise,
    Promise.all(planPromises),
  ]);
  const editable = (
    mechanicsResult.status === 200 &&
    mechanicsResult.envelope.success
  );
  const mechanics = editable
    ? (mechanicsResult.envelope.result || {})
    : {};
  return {
    testingDefaults: mechanics.testing_defaults || [],
    deliveryDefaults: mechanics.delivery_defaults || [],
    approvers: mechanics.approvers || [],
    plansByProject: Object.fromEntries(planEntries),
    flows: flows || [],
    editable,
  };
}

function projectSummary(entries, value) {
  if (!entries.length) return null;
  const labels = [...new Set(entries.map(value).filter(Boolean))];
  return labels.length === 1 ? labels[0] : `${labels.length} defaults`;
}

export function testingSummary(data, workflow) {
  const entries = data.testingDefaults.filter(
    (row) => row.workflow_id === workflow.id,
  );
  const byProject = new Map();
  for (const row of entries) {
    const projectRows = byProject.get(row.project) || [];
    projectRows.push(row);
    byProject.set(row.project, projectRows);
  }
  const parts = [...byProject].map(([project, projectRows]) => (
    `${project} → ${projectSummary(projectRows, (row) => row.plan)}`
  ));
  return parts.length
    ? parts.join(" · ")
    : "Default test plan — set per project.";
}

export function deliverySummary(data, workflow) {
  const entries = data.deliveryDefaults.filter(
    (row) => row.workflow_id === workflow.id,
  );
  const parts = entries.map((row) => `${row.project} → ${row.flow_id}`);
  return parts.length
    ? parts.join(" · ")
    : "Default deployment flow — set per project.";
}

export function approvalSummary(data, workflow) {
  const defaults = workflow.definition?.policies?.approval_defaults || {};
  const actorLabels = new Map(
    data.approvers.map((row) => [Number(row.id), row.label]),
  );
  const order = (workflow.definition?.stages || []).map((stage) => stage.id);
  const transitions = Object.keys(defaults).sort(
    (left, right) => order.indexOf(left) - order.indexOf(right),
  );
  const parts = transitions.map((transitionId) => {
    const gate = defaults[transitionId];
    const who = [
      ...(gate.roles || []).map((role) => ROLE_LABELS[role] || role),
      ...(gate.actors || []).map(
        (actorId) => actorLabels.get(Number(actorId)) || `actor ${actorId}`,
      ),
    ];
    const joiner = gate.mode === "all" ? " and " : " or ";
    return `${transitionId} → ${who.join(joiner)}`;
  });
  return parts.length
    ? parts.join(" · ")
    : "No approval required by default.";
}

export function projectKey(project) {
  return String(project.slug || project.id);
}

export function optionsForProject(data, kind, project) {
  const key = projectKey(project);
  if (kind === "testing") return data.plansByProject[key] || [];
  return data.flows.filter(
    (flow) => flow.project === key && flow.status === "active",
  );
}

export function selectedProjectDefault(data, kind, project, workflowId) {
  const key = projectKey(project);
  const rows = (
    kind === "testing" ? data.testingDefaults : data.deliveryDefaults
  ).filter(
    (row) => row.project === key && row.workflow_id === workflowId,
  );
  if (kind === "testing") {
    const ids = [...new Set(rows.map((row) => Number(row.plan_id)))];
    return ids.length === 1 ? String(ids[0]) : "";
  }
  return rows[0] ? String(rows[0].flow_id) : "";
}

export { ROLE_LABELS };
