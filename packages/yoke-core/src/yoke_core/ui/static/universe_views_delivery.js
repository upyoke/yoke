import {
  buildUniverseRoute,
  serializeScope,
} from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  section,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { renderStageStrip } from "./universe_stage_strip.js";
import {
  isTerminalizable,
  terminalizationDialog,
} from "./deployment_run_terminalization_dialog.js";
import { renderDeliveryFlowExplorer } from "./universe_delivery_flows.js";

function memberLink(documentNode, member) {
  const href = itemDrillInHref({
    projectId: member.project_id,
    projectSequence: member.project_sequence,
    publicRef: member.ref,
  });
  const link = el(
    documentNode,
    href ? "a" : "span",
    "delivery-member",
    [member.ref, member.title].filter(Boolean).join(" · "),
  );
  if (href) link.href = href;
  return link;
}

function originatingItems(documentNode, row) {
  const members = el(documentNode, "div", "delivery-origin-items");
  if ((row.member_items || []).length) {
    for (const member of row.member_items) {
      members.appendChild(memberLink(documentNode, member));
    }
  } else {
    members.appendChild(el(
      documentNode,
      "span",
      "secondary-muted",
      "environment run",
    ));
  }
  return members;
}

function runProjectLabel(projects, projectSlug) {
  const normalized = String(projectSlug || "").toLowerCase();
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value || "").toLowerCase() === normalized,
    )
  ));
  const label = project?.slug || projectSlug || project?.name || "—";
  return project?.emoji ? `${project.emoji} ${label}` : label;
}

function runTimestamp(row) {
  return row.completed_at || row.started_at || row.created_at || null;
}

function renderRunsTable(body, rows, projects, onTerminalized) {
  const documentNode = body.ownerDocument;
  if (!rows.length) {
    body.appendChild(el(documentNode, "p", "empty", "No runs in this scope."));
    return;
  }
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items delivery-runs-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "Run", "Project", "Originating item", "Target",
    "Stages", "Status", "When",
  ]) head.appendChild(el(documentNode, "th", null, label));
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", "mono", row.id || "—"));
    tr.appendChild(el(
      documentNode, "td", null, runProjectLabel(projects, row.project),
    ));
    const item = el(documentNode, "td");
    item.appendChild(originatingItems(documentNode, row));
    tr.appendChild(item);
    tr.appendChild(el(
      documentNode, "td", null,
      row.target_environment || row.target_tier || "—",
    ));
    const stages = el(documentNode, "td");
    stages.appendChild(renderStageStrip(documentNode, row.stages));
    tr.appendChild(stages);
    const status = el(documentNode, "td", "delivery-run-status");
    const pill = statePill(documentNode, row.status, row.status);
    if (pill) status.appendChild(pill);
    if (isTerminalizable(row)) {
      const terminalize = el(
        documentNode, "button", "delivery-run-terminalize", "Terminalize",
      );
      terminalize.type = "button";
      terminalize.addEventListener("click", () => {
        body.appendChild(terminalizationDialog(
          onTerminalized.context,
          row,
          onTerminalized.reload,
        ));
      });
      status.appendChild(terminalize);
    }
    tr.appendChild(status);
    const when = el(documentNode, "td");
    when.appendChild(relativeTime(documentNode, runTimestamp(row)));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  body.appendChild(wrap);
}

export function renderDeliveryRunsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Runs");
  panel.classList.add("delivery-facet-panel");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context,
    panel,
    buckets.map((bucket) => ({
      functionId: "deployment_runs.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      panel.setCount(rows.length);
      renderRunsTable(body, rows, context.projects(), {
        context,
        reload: () => renderDeliveryRunsView(context, main, scope),
      });
      const waiting = rows.filter((row) => row.waiting_on_approval).length;
      if (!waiting) return;
      const inbox = el(
        documentNode,
        "a",
        "delivery-waiting-link",
        `${waiting} run${waiting === 1 ? "" : "s"} waiting on you →`,
      );
      inbox.href = buildUniverseRoute("inbox", serializeScope(scope));
      body.appendChild(inbox);
    },
  );
}

export function renderDeliveryFlowsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Flows");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context,
    panel,
    buckets.map((bucket) => ({
      functionId: "workflows.definition.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.flows);
      renderDeliveryFlowExplorer(body, panel, rows);
    },
  );
}
