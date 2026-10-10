import { elapsedSeconds, SECONDS_PER_DAY } from "./universe_time.js";
import { instantMicros } from "./timestamps.js";
import { attachTooltip } from "./universe_tooltip.js";
import {
  el,
  labelCellsByColumn,
} from "./universe_view_support.js";
import { executionTargetLabel } from "./qa_execution_target_view.js";
import {
  loadProjectCalls,
  methodIcon,
  outcomeNode,
  qaPanel,
  qaRoute,
  relativeTimeNode,
  showFailure,
  tableWrap,
} from "./qa_view_primitives.js";

const PLAN_OUTCOME_ORDER = new Map([
  ["needs_review", 0],
  ["failed", 1],
  ["running", 2],
  ["waiting", 3],
  ["queued", 4],
  ["passed", 5],
]);
function attachmentTransition(row) {
  const transitionId = String(row.transition_id || "");
  if (transitionId === "reviewed-implementation") return "review";
  return transitionId || row.transition_label || "unassigned";
}

function attachmentText(attachments) {
  if (!attachments?.length) return "not attached";
  return attachments.map((row) => {
    if (row.kind === "item") {
      return `item · ${row.item_ref || row.public_ref}`;
    }
    return `project default · ${attachmentTransition(row)}`;
  }).join(" · ");
}

function summarySeparator(documentNode) {
  return el(documentNode, "span", "qa-summary-separator", "·");
}

function methodSummary(documentNode, row) {
  const wrap = el(documentNode, "span", "qa-method-summary");
  wrap.appendChild(el(
    documentNode, "strong", null, String(row.case_count),
  ));
  const methods = row.method_presentations || (row.method_ids || []).map(
    (id) => ({ id }),
  );
  if (methods.length) wrap.appendChild(summarySeparator(documentNode));
  for (const method of methods) {
    const icon = el(
      documentNode, "span", "qa-method-glyph", methodIcon(method),
    );
    attachTooltip(documentNode, icon, method.id);
    wrap.appendChild(icon);
  }
  const groups = [...new Set(methods.map((method) => method.group).filter(Boolean))];
  if (groups.length === 1) {
    wrap.appendChild(el(documentNode, "span", null, groups[0]));
  }
  if (Number(row.materialized_requirement_count) > Number(row.case_count)) {
    wrap.appendChild(summarySeparator(documentNode));
    wrap.appendChild(el(
      documentNode, "span", "qa-baseline-count",
      `${row.materialized_requirement_count} ` +
        `${Number(row.materialized_requirement_count) === 1 ? "req" : "reqs"} × baseline`,
    ));
  }
  return wrap;
}

function orderedPlans(rows) {
  return [...rows].sort((left, right) => {
    const leftRank = PLAN_OUTCOME_ORDER.get(left.last_outcome) ?? 99;
    const rightRank = PLAN_OUTCOME_ORDER.get(right.last_outcome) ?? 99;
    if (leftRank !== rightRank) return leftRank - rightRank;
    const leftTime = left.last_at == null ? null : instantMicros(left.last_at);
    const rightTime = right.last_at == null ? null : instantMicros(right.last_at);
    if (leftTime !== rightTime) {
      if (leftTime === null) return 1;
      if (rightTime === null) return -1;
      return leftTime < rightTime ? 1 : -1;
    }
    return left.slug.localeCompare(right.slug);
  });
}

function planResultAge(documentNode, value) {
  const now = Date.now();
  const age = relativeTimeNode(documentNode, value, now);
  const seconds = elapsedSeconds(value, now);
  if (seconds !== null && seconds >= SECONDS_PER_DAY && seconds < SECONDS_PER_DAY * 2) {
    age.textContent = "yesterday";
  }
  return age;
}

function renderPlanTable(context, body, rows) {
  const documentNode = context.document;
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty",
      "No test plans in this project scope yet.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items qa-plans-table table-stacks-narrow");
  const head = el(documentNode, "tr");
  const columns = [
    "Plan", "Project", "Target", "Cases", "Attached", "Last result",
  ];
  for (const label of columns) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of orderedPlans(rows)) {
    const href = qaRoute(
      context, "plans", String(row.id), row.project,
    );
    const tr = el(documentNode, "tr");
    const planCell = el(documentNode, "td");
    const link = el(documentNode, "a", "qa-plan-button", row.slug);
    link.href = href;
    planCell.appendChild(link);
    tr.appendChild(planCell);
    tr.appendChild(el(documentNode, "td", null, row.project));
    const target = row.execution_target;
    tr.appendChild(el(
      documentNode,
      "td",
      target ? "qa-plan-target" : "qa-plan-target muted",
      executionTargetLabel(target),
    ));
    const methods = el(documentNode, "td");
    methods.appendChild(methodSummary(documentNode, row));
    tr.appendChild(methods);
    tr.appendChild(el(
      documentNode, "td", null, attachmentText(row.attachments),
    ));
    const result = el(documentNode, "td");
    const displayLabel = row.last_outcome === "needs_review"
      ? "1 needs review"
      : null;
    result.appendChild(outcomeNode(
      documentNode, row.last_outcome || "not run", null, displayLabel,
    ));
    if (row.last_verdict_reason) {
      const reason = el(documentNode, "details", "qa-result-reason");
      reason.appendChild(el(documentNode, "summary", null, "Verdict details"));
      reason.appendChild(el(documentNode, "p", null, row.last_verdict_reason));
      result.appendChild(reason);
    }
    if (row.last_at) {
      result.appendChild(el(documentNode, "span", "qa-result-age", " "));
      result.appendChild(planResultAge(documentNode, row.last_at));
    }
    tr.appendChild(result);
    labelCellsByColumn(tr, columns);
    table.appendChild(tr);
  }
  body.appendChild(tableWrap(documentNode, table));
}

export async function renderQaPlans(context, main, scope) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", "loading test plans…",
  ));
  const { callResults, failed } = await loadProjectCalls(
    context, scope, "qa.plan.list", {},
  );
  if (!context.isMounted()) return;
  if (failed) {
    showFailure(documentNode, main, failed);
    return;
  }
  const rows = callResults.flatMap(
    (result) => result.envelope.result?.rows || [],
  );
  const result = qaPanel(
    documentNode,
    "Test plans",
    rows.length,
  );
  renderPlanTable(context, result.body, rows);
  const note = el(documentNode, "div", "qa-panel-note");
  const example = orderedPlans(rows)[0];
  note.appendChild(el(
    documentNode,
    "code",
    "qa-inline-command",
    `yoke qa plan create --project ${example?.project || "<project>"} ` +
      `${example?.slug || "<slug>"}`,
  ));
  note.appendChild(el(
    documentNode,
    "span",
    null,
    " — plans and cases are created and edited through registered surfaces.",
  ));
  if (rows.some((row) => row.slug === "full-verification")
    && rows.some((row) => row.slug === "e2e-suite")) {
    note.appendChild(el(
      documentNode,
      "span",
      null,
      " full-verification and e2e-suite are yoke's migrated registered " +
        "test commands.",
    ));
  }
  result.root.appendChild(note);
  main.replaceChildren(result.root);
}

export { renderQaPlanDetail } from "./qa_plan_detail_view.js";
