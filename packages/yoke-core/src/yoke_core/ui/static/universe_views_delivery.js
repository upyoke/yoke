import {
  buildUniverseRoute,
  serializeScope,
} from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";
import {
  deliveryStageBar,
  labelledFact,
  metricStrip,
  stageProgress,
} from "./universe_secondary_primitives.js";
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

function runCard(documentNode, row, scope) {
  const card = el(documentNode, "article", "delivery-run-card");
  const header = el(documentNode, "div", "delivery-run-header");
  const identity = el(documentNode, "div");
  identity.appendChild(el(documentNode, "h3", null, row.id || "Run"));
  const subtitle = [
    row.flow,
    row.target_env,
    (Array.isArray(scope) && scope.length === 1) ? null : row.project,
  ].filter(Boolean).join(" · ");
  identity.appendChild(el(
    documentNode,
    "p",
    "delivery-run-subtitle",
    subtitle,
  ));
  header.appendChild(identity);
  const status = statePill(documentNode, row.status, row.status);
  if (status) header.appendChild(status);
  card.appendChild(header);

  const facts = el(documentNode, "div", "session-facts");
  facts.appendChild(labelledFact(
    documentNode,
    "Progress",
    stageProgress(
      documentNode,
      row.stage_index,
      row.stage_count,
      row.current_stage || "not started",
    ),
  ));
  facts.appendChild(labelledFact(
    documentNode,
    "Created",
    relativeTime(documentNode, row.created_at),
  ));
  facts.appendChild(labelledFact(
    documentNode,
    "Initiated by",
    row.created_by || "operator",
  ));
  facts.appendChild(labelledFact(
    documentNode,
    "Release lineage",
    row.release_lineage || "—",
  ));
  card.appendChild(facts);
  card.appendChild(deliveryStageBar(documentNode, row.stages || []));

  const members = el(documentNode, "div", "delivery-members");
  if ((row.member_items || []).length) {
    for (const member of row.member_items) {
      members.appendChild(memberLink(documentNode, member));
    }
  } else {
    members.appendChild(el(
      documentNode,
      "span",
      "secondary-muted",
      "Environment run · no member items",
    ));
  }
  card.appendChild(members);

  if (row.waiting_on_approval) {
    const footer = el(documentNode, "div", "delivery-approval-footer");
    footer.appendChild(el(
      documentNode,
      "span",
      null,
      `Waiting for approval at ${row.current_stage || "the current stage"}`,
    ));
    const inbox = el(documentNode, "a", "row-link", "Open Inbox →");
    inbox.href = buildUniverseRoute("inbox", serializeScope(scope));
    footer.appendChild(inbox);
    card.appendChild(footer);
  }
  return card;
}

export function renderDeliveryRunsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Runs");
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
      body.appendChild(metricStrip(documentNode, [
        { label: "runs", value: rows.length },
        {
          label: "in progress",
          value: rows.filter((row) => (
            ["created", "executing"].includes(row.status)
          )).length,
        },
        {
          label: "needs approval",
          value: rows.filter((row) => row.waiting_on_approval).length,
          tone: "warn",
        },
        {
          label: "succeeded",
          value: rows.filter((row) => row.status === "succeeded").length,
          tone: "good",
        },
        {
          label: "failed",
          value: rows.filter((row) => row.status === "failed").length,
          tone: "bad",
        },
      ]));
      if (!rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "no runs yet"));
        return;
      }
      const list = el(documentNode, "div", "delivery-run-list");
      for (const row of rows) list.appendChild(runCard(documentNode, row, scope));
      body.appendChild(list);
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
      panel.setCount(rows.length);
      body.appendChild(metricStrip(documentNode, [
        { label: "flows", value: rows.length },
        {
          label: "active",
          value: rows.filter((row) => row.status === "active").length,
          tone: "good",
        },
        {
          label: "disabled",
          value: rows.filter((row) => row.status === "disabled").length,
        },
        {
          label: "declared stages",
          value: rows.reduce(
            (total, row) => total + (row.stage_names || []).length,
            0,
          ),
        },
      ]));
      renderTable(body, rows, withProjectColumn([
        { label: "flow", value: (row) => row.id, mono: true },
        { label: "name", value: (row) => row.name },
        { label: "target env", value: (row) => row.target_env },
        { label: "status", value: (row) => row.status, pill: true },
        {
          label: "stages",
          value: (row) => (row.stage_names || []).join(" → "),
        },
        { label: "on failure", value: (row) => row.on_failure },
      ], scope, (row) => row.project), "no deployment flows declared");
    },
  );
}
