import { el } from "./universe_view_support.js";
import {
  loadProjectCalls,
  outcomeNode,
  showFailure,
} from "./qa_view_primitives.js";

function todayRows(rows) {
  const today = new Date().toISOString().slice(0, 10);
  return rows.filter(
    (row) => String(row.happened_at || "").slice(0, 10) === today,
  );
}
function stat(documentNode, value, label) {
  const card = el(documentNode, "div", "qa-stat");
  card.appendChild(el(documentNode, "strong", null, String(value)));
  card.appendChild(el(documentNode, "span", null, label));
  return card;
}

function evidenceText(row) {
  const count = Number(row.evidence_count || 0);
  if (row.capture_degraded_reason) {
    return count
      ? `${count} artifacts · text capture + reason`
      : "text capture + reason";
  }
  return count ? `${count} ${count === 1 ? "artifact" : "artifacts"}` : "—";
}

function renderActivityTable(documentNode, body, rows) {
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "No materialized case activity yet.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items qa-activity-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "Plan", "Case", "Method", "Outcome", "Evidence", "When",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", "mono", row.plan));
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
    tr.appendChild(el(documentNode, "td", null, evidenceText(row)));
    tr.appendChild(el(documentNode, "td", null, row.happened_at || "—"));
    table.appendChild(tr);
  }
  body.appendChild(table);
}

export async function renderQaActivity(context, main, scope) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", "loading QA activity…",
  ));
  const { callResults, failed } = await loadProjectCalls(
    context, scope, "qa.activity.list", { limit: 100 },
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
    ));
  const today = todayRows(rows);
  const stats = el(documentNode, "div", "qa-stats");
  stats.appendChild(stat(documentNode, today.length, "case runs today"));
  stats.appendChild(stat(
    documentNode,
    today.filter((row) => row.outcome === "passed").length,
    "passed",
  ));
  stats.appendChild(stat(
    documentNode,
    today.filter((row) => row.outcome === "needs_review").length,
    "needs review",
  ));
  stats.appendChild(stat(
    documentNode,
    today.filter((row) => row.outcome === "running").length,
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
  renderActivityTable(documentNode, body, rows);
  panel.appendChild(body);
  const note = el(documentNode, "div", "qa-panel-note");
  note.textContent =
    "Blocked on precondition is neither a pass nor a case failure. " +
    "Passed · capture degraded keeps paired text evidence and the explicit " +
    "reason; missing evidence never renders as a satisfied outcome.";
  panel.appendChild(note);
  main.replaceChildren(stats, panel);
}
