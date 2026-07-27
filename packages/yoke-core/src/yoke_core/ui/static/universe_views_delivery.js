import {
  buildUniverseRoute,
  serializeScope,
} from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  section,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

function memberLink(documentNode, member) {
  const link = el(
    documentNode,
    "a",
    "delivery-member",
    [member.ref, member.title].filter(Boolean).join(" · "),
  );
  link.href = buildUniverseRoute(
    "items",
    String(member.project_id),
    String(member.ref || member.id).replace(/^[A-Za-z]+-/, ""),
  );
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

function runStages(documentNode, row) {
  const stages = row.stages || [];
  const strip = el(documentNode, "span", "delivery-run-stages");
  strip.setAttribute("role", "img");
  strip.setAttribute(
    "aria-label",
    stages.length
      ? `stages: ${stages.map((stage) => (
        `${stage.name || "unnamed"} ${stage.state || "pending"}`
      )).join(", ")}`
      : "no stages published",
  );
  for (const stage of stages) {
    const state = String(stage.state || "pending");
    const segment = el(documentNode, "span", "delivery-run-stage");
    segment.setAttribute("data-state", state);
    segment.setAttribute("title", `${stage.name || "unnamed"} · ${state}`);
    strip.appendChild(segment);
  }
  return strip;
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

function renderRunsTable(body, rows, projects) {
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
    tr.appendChild(el(documentNode, "td", null, row.target_env || "—"));
    const stages = el(documentNode, "td");
    stages.appendChild(runStages(documentNode, row));
    tr.appendChild(stages);
    const status = el(documentNode, "td");
    const pill = statePill(documentNode, row.status, row.status);
    if (pill) status.appendChild(pill);
    tr.appendChild(status);
    const when = el(documentNode, "td");
    when.appendChild(relativeTime(documentNode, runTimestamp(row)));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  body.appendChild(wrap);
}

function flowLabel(row, scope) {
  const identity = row.name || row.id || "unnamed flow";
  return Array.isArray(scope) && scope.length === 1
    ? identity
    : `${row.project || "project unavailable"} · ${identity}`;
}

function renderFlowPipeline(documentNode, detail, row) {
  detail.replaceChildren();
  const stages = row.stage_names || [];
  if (!stages.length) {
    detail.appendChild(el(
      documentNode, "p", "empty", "No stages published for this flow.",
    ));
    return;
  }
  const pipeline = el(documentNode, "div", "delivery-flow-pipeline");
  pipeline.setAttribute("aria-label", `Flow stages: ${stages.join(", ")}`);
  for (const [index, stage] of stages.entries()) {
    if (index > 0) {
      const arrow = el(documentNode, "span", "delivery-flow-arrow", "→");
      arrow.setAttribute("aria-hidden", "true");
      pipeline.appendChild(arrow);
    }
    pipeline.appendChild(el(
      documentNode, "div", "delivery-flow-stage", stage,
    ));
  }
  detail.appendChild(pipeline);
}

function renderFlowDetail(body, panel, rows, scope) {
  const documentNode = body.ownerDocument;
  if (!rows.length) {
    panel.setCount(0);
    body.appendChild(el(
      documentNode, "p", "empty", "No deployment flows declared.",
    ));
    return;
  }
  let selected = rows[0];
  const detail = el(documentNode, "div", "delivery-flow-detail");
  const choices = el(documentNode, "div", "delivery-flow-selector");
  const buttons = rows.map((row) => {
    const button = el(
      documentNode, "button", "delivery-flow-choice", flowLabel(row, scope),
    );
    button.type = "button";
    choices.appendChild(button);
    return [button, row];
  });
  const paint = () => {
    panel.setCount(null);
    panel.children[0].children[0].textContent =
      `Flow · ${selected.id || "unnamed"}`;
    panel.setCount((selected.stage_names || []).length);
    for (const [button, row] of buttons) {
      const active = row === selected;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    }
    renderFlowPipeline(documentNode, detail, selected);
  };
  for (const [button, row] of buttons) {
    button.addEventListener("click", () => {
      selected = row;
      paint();
    });
  }
  if (rows.length > 1) {
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", "Deployment flows");
    body.appendChild(choices);
  }
  body.appendChild(detail);
  paint();
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
      renderRunsTable(body, rows, context.projects());
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
      renderFlowDetail(body, panel, rows, scope);
    },
  );
}
