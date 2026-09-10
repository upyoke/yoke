import { attachTooltip } from "./universe_tooltip.js";
import {
  el,
  withProjectColumn,
} from "./universe_view_support.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import {
  loadProjectCalls,
  outcomeNode,
  qaRoute,
  relativeTimeNode,
  showFailure,
  tableWrap,
} from "./qa_view_primitives.js";

const RECENT_ACTIVITY_LIMIT = 6;
// Three pictures fit a table row; the rest fold behind "+N more".
const ACTIVITY_EVIDENCE_SHOWN = 3;

function todayRows(rows) {
  const today = new Date().toISOString().slice(0, 10);
  return rows.filter(
    (row) => String(row.happened_at || "").slice(0, 10) === today,
  );
}

function summarizeRows(rows) {
  const today = todayRows(rows);
  const counts = {};
  for (const row of today) {
    const outcome = String(row.outcome || "queued");
    counts[outcome] = Number(counts[outcome] || 0) + 1;
  }
  return { total: today.length, counts };
}

function resultSummary(result) {
  const payload = result.envelope.result || {};
  const summary = payload.summary;
  if (
    summary
    && Number.isFinite(Number(summary.total))
    && summary.counts
    && typeof summary.counts === "object"
    && !Array.isArray(summary.counts)
  ) {
    return summary;
  }
  return summarizeRows(payload.rows || []);
}

function aggregateSummaries(callResults) {
  const aggregate = { total: 0, counts: {} };
  for (const result of callResults) {
    const summary = resultSummary(result);
    aggregate.total += Number(summary.total);
    for (const [outcome, rawCount] of Object.entries(summary.counts)) {
      const count = Number(rawCount);
      if (!Number.isFinite(count)) continue;
      aggregate.counts[outcome] =
        Number(aggregate.counts[outcome] || 0) + count;
    }
  }
  return aggregate;
}

function stat(documentNode, value, label) {
  const card = el(documentNode, "div", "qa-stat");
  card.appendChild(el(documentNode, "strong", null, String(value)));
  card.appendChild(el(documentNode, "span", null, label));
  return card;
}

function evidenceText(row) {
  if (row.proof_summary) return row.proof_summary;
  const count = Number(row.evidence_count || 0);
  if (row.capture_degraded_reason) {
    return count
      ? `${count} artifacts · text capture + reason`
      : "text capture + reason";
  }
  return count ? `${count} ${count === 1 ? "artifact" : "artifacts"}` : "—";
}

// The pictures behind the row, drawn through the same strip every review
// surface uses — a count alone gave this table's reader a number and no
// way to look at the screenshot it counted.
function evidenceCell(context, documentNode, row) {
  const td = el(documentNode, "td", "qa-activity-evidence");
  const artifacts = Array.isArray(row.artifacts) ? row.artifacts : [];
  const summary = el(
    documentNode, "div", "qa-activity-evidence-summary", evidenceText(row),
  );
  if (row.verdict_reason) attachTooltip(documentNode, summary, row.verdict_reason);
  td.appendChild(summary);
  const strip = evidenceStrip(context, artifacts, {
    compact: true, requirementId: row.requirement_id, limit: ACTIVITY_EVIDENCE_SHOWN,
  });
  if (strip) td.appendChild(strip);
  // The row itself navigates to its plan on click; a thumbnail opens its
  // picture and must not also trigger that.
  td.addEventListener("click", (event) => event.stopPropagation());
  return td;
}

// Whether a person still has to answer for this row. Only a pending review
// is served, so the cell either points at the Inbox card or says the row
// needs nobody.
function reviewCell(context, documentNode, row, pending) {
  const td = el(documentNode, "td", "qa-activity-review");
  const request = pending.get(String(row.requirement_id));
  if (request) {
    const link = el(documentNode, "a", "review-pill is-pending", "needs your review →");
    link.href = buildUniverseRoute("inbox", request.project_id);
    td.appendChild(link);
  } else {
    td.appendChild(el(documentNode, "span", "secondary-muted", "—"));
  }
  return td;
}

function activityProjectLabel(context, row) {
  const rowLabel = row.project_slug || row.project;
  const rowKey = row.project_id ?? rowLabel;
  const project = context.projects().find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(rowKey),
    )
  ));
  return String(
    rowLabel || project?.slug || project?.name || row.project_id || "—",
  );
}

function renderActivityTable(context, body, rows, scope, pending) {
  const documentNode = context.document;
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "No materialized case activity yet.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items qa-activity-table");
  const columns = withProjectColumn([
    { label: "Plan" },
    { label: "Case" },
    { label: "Method" },
    { label: "Outcome" },
    { label: "Evidence" },
    { label: "Review" },
    { label: "When" },
  ], scope, (row) => activityProjectLabel(context, row));
  const projectColumn = columns.find((column) => column.label === "project");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const href = qaRoute(
      context, "plans", String(row.plan_id), row.project,
    );
    const tr = el(documentNode, "tr", "qa-clickable-row");
    tr.addEventListener("click", (event) => {
      if (event.target?.closest?.("a")) return;
      context.navigate(href);
    });
    const plan = el(documentNode, "td");
    const planLink = el(documentNode, "a", "mono qa-activity-link", row.plan);
    planLink.href = href;
    plan.appendChild(planLink);
    tr.appendChild(plan);
    if (projectColumn) {
      tr.appendChild(el(
        documentNode,
        "td",
        "qa-activity-project",
        projectColumn.value(row),
      ));
    }
    const caseLabel = row.host_baseline
      ? `${row.case_key} @${row.host_baseline}` : row.case_key;
    tr.appendChild(el(documentNode, "td", "mono", caseLabel));
    tr.appendChild(el(
      documentNode, "td", null, row.method_name || row.method_id || "—",
    ));
    const outcome = el(documentNode, "td");
    outcome.appendChild(outcomeNode(
      documentNode, row.outcome, row.capture_degraded_reason,
    ));
    tr.appendChild(outcome);
    tr.appendChild(evidenceCell(context, documentNode, row));
    tr.appendChild(reviewCell(context, documentNode, row, pending));
    const when = el(documentNode, "td");
    when.appendChild(relativeTimeNode(documentNode, row.happened_at));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  body.appendChild(tableWrap(documentNode, table));
}

export async function renderQaActivity(
  context, main, scope, deploymentRunId = null, navigation = {},
) {
  deploymentRunId = typeof deploymentRunId === "string" ? deploymentRunId : null;
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", "loading QA activity…",
  ));
  const [{ callResults, failed }, pending] = await Promise.all([
    loadProjectCalls(
      context,
      scope,
      "qa.activity.list",
      {
        limit: deploymentRunId ? 100 : RECENT_ACTIVITY_LIMIT,
        ...(deploymentRunId ? { deployment_run_id: deploymentRunId } : {}),
      },
    ),
    loadPendingReviews(
      context, scope === "all" ? context.projects().map((row) => row.id) : scope,
    ),
  ]);
  if (!context.isMounted()) return;
  if (failed) {
    showFailure(documentNode, main, failed);
    return;
  }
  const rows = callResults.flatMap(
    (result) => result.envelope.result?.rows || [],
  ).sort((left, right) =>
    String(right.happened_at || "").localeCompare(
      String(left.happened_at || ""),
    )).slice(0, deploymentRunId ? 100 : RECENT_ACTIVITY_LIMIT);
  const summary = aggregateSummaries(callResults);
  const counts = summary.counts;
  const stats = el(documentNode, "div", "qa-stats");
  stats.appendChild(stat(documentNode, summary.total, "case runs today"));
  stats.appendChild(stat(
    documentNode,
    counts.passed || 0,
    "passed",
  ));
  stats.appendChild(stat(
    documentNode,
    counts.needs_review || 0,
    "needs review",
  ));
  stats.appendChild(stat(
    documentNode,
    counts.running || 0,
    "running",
  ));
  const panel = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Recent case runs"));
  header.appendChild(el(
    documentNode,
    "span",
    "qa-panel-context",
    deploymentRunId
      ? `Evidence for ${deploymentRunId}`
      : "requirements, runs and artifacts rendered as one outcome",
  ));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  renderActivityTable(context, body, rows, scope, pending);
  panel.appendChild(body);
  const note = el(documentNode, "div", "qa-panel-note");
  note.textContent =
    "Blocked on precondition is neither a pass nor a case failure — " +
    "the case's host baseline could not be reached or verified. " +
    "Passed · capture degraded keeps the paired text evidence plus the " +
    "explicit reason; missing evidence never renders as a satisfied outcome.";
  panel.appendChild(note);
  main.replaceChildren(stats, panel);
  if (deploymentRunId && typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(deploymentRunId);
  }
}
