import {
  el,
  withProjectColumn,
} from "./universe_view_support.js";
import {
  loadProjectCalls,
  outcomeNode,
  qaRoute,
  relativeTimeNode,
  showFailure,
  tableWrap,
} from "./qa_view_primitives.js";

const RECENT_ACTIVITY_LIMIT = 6;

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

function renderActivityTable(context, body, rows, scope) {
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
    const evidence = el(documentNode, "td", null, evidenceText(row));
    if (row.verdict_reason) evidence.title = row.verdict_reason;
    tr.appendChild(evidence);
    const when = el(documentNode, "td");
    when.appendChild(relativeTimeNode(documentNode, row.happened_at));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  body.appendChild(tableWrap(documentNode, table));
}

export async function renderQaActivity(context, main, scope) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", "loading QA activity…",
  ));
  const { callResults, failed } = await loadProjectCalls(
    context, scope, "qa.activity.list", { limit: RECENT_ACTIVITY_LIMIT },
  );
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
    )).slice(0, RECENT_ACTIVITY_LIMIT);
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
    "requirements, runs and artifacts rendered as one outcome",
  ));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  renderActivityTable(context, body, rows, scope);
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
