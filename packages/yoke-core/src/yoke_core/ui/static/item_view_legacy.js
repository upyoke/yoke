/* Rolling-cutover fallback for hosts that have not registered item page reads. */

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadSection,
  renderTable,
  section,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";

export const LEGACY_ITEM_FIELDS = [
  "id", "title", "workflow_id", "workflow_version_id", "status",
  "priority", "blocked", "blocked_reason", "project",
];

function isBlocked(row) {
  return Number(row.blocked) === 1;
}

export function renderLegacyItems(
  body,
  rows,
  scope,
  projects,
) {
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  const rowProject = (row) => (
    (Array.isArray(scope) && scope.length === 1)
      ? scope[0]
      : (idBySlug.get(String(row.project)) || String(row.project))
  );
  renderTable(body, rows, withProjectColumn([
    { label: "id", value: (row) => row.id },
    { label: "workflow", value: (row) => row.workflow_id },
    { label: "version", value: (row) => row.workflow_version_id },
    { label: "title", value: (row) => row.title },
    { label: "status", value: (row) => row.status, pill: true },
    { label: "priority", value: (row) => row.priority },
    {
      label: "blocked",
      value: (row) => (
        isBlocked(row) ? (row.blocked_reason || "blocked") : ""
      ),
    },
  ], scope, (row) => row.project), "no items yet",
  (row) => buildUniverseRoute("items", rowProject(row), String(row.id)));
}

function legacySummary(documentNode, fields) {
  const summary = el(documentNode, "table", "items kv");
  for (const [label, value] of [
    ["workflow", fields.workflow_id],
    ["workflow version", fields.workflow_version_id],
    ["status", fields.status],
    ["priority", fields.priority],
    ["flow", fields.flow],
    ["project", fields.project],
    ["created", fields.created_at],
  ]) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "th", null, label));
    const cell = el(documentNode, "td");
    const pill = label === "status"
      ? statePill(documentNode, value) : null;
    if (pill) cell.appendChild(pill);
    else cell.textContent = String(value ?? "");
    tr.appendChild(cell);
    summary.appendChild(tr);
  }
  return summary;
}

function legacyTasks(context, main, projectId, fields) {
  if (fields.workflow_id !== "epic") return;
  const tasks = section(context.document, "Tasks");
  main.appendChild(tasks);
  loadSection(
    context,
    tasks,
    "epic_tasks.list.run",
    {},
    (body, taskResult) => {
      const rows = (taskResult.envelope.result || {}).tasks || [];
      renderTable(body, rows, [
        { label: "#", value: (row) => row.task_num },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status, pill: true },
      ], "no tasks yet");
    },
    {
      kind: "epic_task",
      epic_id: Number(fields.id),
      project_id: String(projectId),
    },
  );
}

export function renderLegacyItemDetail(
  context,
  main,
  projectId,
  itemRef,
  callResult,
) {
  const documentNode = context.document;
  const panel = section(documentNode, `Item ${itemRef}`);
  main.replaceChildren(panel);
  panel.renderEnvelope(callResult, (body, result) => {
    const fields = (result.envelope.result || {}).fields || {};
    body.appendChild(legacySummary(documentNode, fields));
    const rendered = String(fields.body || "").trim();
    body.appendChild(el(
      documentNode,
      rendered ? "pre" : "p",
      rendered ? "item-body" : "empty",
      rendered || "no body yet",
    ));
    legacyTasks(context, main, projectId, fields);
  });
}
