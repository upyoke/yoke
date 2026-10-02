import { attachTooltip } from "./universe_tooltip.js";
import {
  el,
  labelCellsByColumn,
  withProjectColumn,
} from "./universe_view_support.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { activityHistory } from "./qa_activity_history.js";
import { qaCaseItemRefLoader, qaCaseName } from "./qa_case_name.js";
import { evidenceSummaryNode } from "./qa_run_conclusion.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
import {
  classifyQaRow,
  loadProjectCalls,
  outcomeNode,
  qaRoute,
  relativeTimeNode,
  showFailure,
  tableWrap,
} from "./qa_view_primitives.js";

// The read's largest page. The table lists every case run of the day the
// summary counts, so "30 case runs today" sits above thirty rows; a fixed
// short page cut the list off and hid whichever cases ran first.
const ACTIVITY_PAGE_LIMIT = 500;
// Three pictures fit a table row; the rest fold behind "+N more".
const ACTIVITY_EVIDENCE_SHOWN = 3;

function todayRows(rows, day = new Date().toISOString().slice(0, 10)) {
  const today = day;
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
  const summary = evidenceSummaryNode(
    documentNode, row, evidenceText(row), "qa-activity-evidence-summary",
  );
  if (row.verdict_reason) attachTooltip(documentNode, summary, row.verdict_reason);
  td.appendChild(summary);
  const strip = evidenceStrip(context, artifacts, {
    compact: true, requirementId: row.requirement_id, limit: ACTIVITY_EVIDENCE_SHOWN,
  });
  if (strip) td.appendChild(strip);
  return td;
}

// A case attached straight to an item or a deployment run has no plan, so
// the cell says so rather than linking to a plan page that does not exist.
// A missing plan is a real attachment shape here, not a failed lookup.
function planCell(context, documentNode, row) {
  const td = el(documentNode, "td");
  if (row.plan_id == null) {
    td.appendChild(el(documentNode, "span", "secondary-muted", "no plan"));
    return td;
  }
  const link = el(
    documentNode, "a", "mono qa-activity-link", row.plan || String(row.plan_id),
  );
  link.href = qaRoute(context, "plans", String(row.plan_id), row.project);
  td.appendChild(link);
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

function renderActivityTable(context, body, rows, scope, pending, labelCase) {
  const documentNode = context.document;
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "No QA case activity yet.",
    ));
    return;
  }
  const table = el(
    documentNode, "table", "items qa-activity-table table-stacks-narrow",
  );
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
    // Each subject keeps its own link — the case name opens the case, the
    // plan its plan, a thumbnail its picture — and the row itself is not a
    // link, so a click never lands somewhere its reader did not point at.
    const href = qaRoute(
      context, "activity", String(row.requirement_id), row.project,
    );
    const tr = el(documentNode, "tr", "qa-activity-row");
    tr.appendChild(planCell(context, documentNode, row));
    if (projectColumn) {
      tr.appendChild(el(
        documentNode,
        "td",
        "qa-activity-project",
        projectColumn.value(row),
      ));
    }
    const caseCell = el(documentNode, "td", "qa-activity-case");
    const caseLink = el(
      documentNode, "a", "qa-activity-link",
      qaCaseName(row),
    );
    caseLink.href = href;
    labelCase(caseLink, row);
    caseCell.appendChild(caseLink);
    tr.appendChild(caseCell);
    tr.appendChild(el(
      documentNode, "td", null, row.method_name || row.method_id || "—",
    ));
    const outcome = el(documentNode, "td");
    const classified = classifyQaRow(row, rows);
    outcome.appendChild(outcomeNode(
      documentNode,
      row.outcome,
      row.capture_degraded_reason,
      classified?.label,
      classified?.detail,
    ));
    tr.appendChild(outcome);
    tr.appendChild(evidenceCell(context, documentNode, row));
    tr.appendChild(reviewCell(context, documentNode, row, pending));
    const when = el(documentNode, "td");
    when.appendChild(relativeTimeNode(documentNode, row.happened_at));
    tr.appendChild(when);
    // Seven columns do not fit a phone. Each cell keeps its column's name so
    // the row can stack, because the facts a reader opens this screen for —
    // the outcome, its evidence, whether it is waiting on a review — are the
    // ones a horizontal scroller puts off the right edge.
    labelCellsByColumn(tr, columns.map((column) => column.label));
    table.appendChild(tr);
  }
  body.appendChild(tableWrap(documentNode, table));
}

export async function renderQaActivity(context, main, scope) {
  const documentNode = context.document;
  const signal = context.signal;
  const active = () => context.isMounted() && !signal?.aborted;
  const loading = el(
    documentNode, "p", "empty", "loading QA activity…",
  );
  main.replaceChildren(loading);
  const [{ callResults, failed }, pending] = await Promise.all([
    loadProjectCalls(
      context, scope, "qa.activity.list", { limit: ACTIVITY_PAGE_LIMIT },
    ),
    loadPendingReviews(
      context, scope === "all" ? context.projects().map((row) => row.id) : scope,
    ),
  ]);
  if (!active() || !main.contains(loading)) return;
  if (failed) {
    showFailure(documentNode, main, failed);
    return;
  }
  const recent = callResults.flatMap(
    (result) => result.envelope.result?.rows || [],
  ).sort((left, right) =>
    String(right.happened_at || "").localeCompare(
      String(left.happened_at || ""),
  ));
  const rows = recent;
  const loadItemRef = qaCaseItemRefLoader(context);
  const labelCase = (link, row) => queueMicrotask(async () => {
    // Only visible links need names. Keep the usable table and focused link
    // in place while optional reads finish; navigation/filtering may remove it.
    if (!active() || !main.contains(link)) return;
    const ref = await loadItemRef(row);
    if (ref && active() && main.contains(link)) link.textContent = qaCaseName(row, ref);
  });
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
  stats.appendChild(stat(documentNode, counts.failed || 0, "failed"));
  const panel = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Recent case runs"));
  header.appendChild(el(
    documentNode,
    "span",
    "qa-panel-context",
    "requirements, runs and artifacts rendered as one outcome",
  ));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(activityHistory(context, rows, (host, page) => {
    renderActivityTable(context, host, page, scope, pending, labelCase);
  }));
  panel.appendChild(body);
  const note = el(documentNode, "div", "qa-panel-note");
  note.textContent =
    "Blocked on precondition is neither a pass nor a case failure — " +
    "the case's host baseline could not be reached or verified. " +
    "Passed · capture degraded keeps the paired text evidence plus the " +
    "explicit reason; missing evidence never renders as a satisfied outcome.";
  panel.appendChild(note);
  main.replaceChildren(stats, panel);
}
