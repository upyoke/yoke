import {
  el,
} from "./universe_view_support.js";
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
  ["passed", 1],
  ["running", 2],
  ["waiting", 3],
  ["queued", 4],
  ["failed", 5],
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
      return `item · ${row.item_ref || row.item_id}`;
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
    icon.title = method.id;
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
      `${row.materialized_requirement_count} reqs × baseline`,
    ));
  }
  return wrap;
}

function orderedPlans(rows) {
  return [...rows].sort((left, right) => {
    const leftRank = PLAN_OUTCOME_ORDER.get(left.last_outcome) ?? 99;
    const rightRank = PLAN_OUTCOME_ORDER.get(right.last_outcome) ?? 99;
    if (leftRank !== rightRank) return leftRank - rightRank;
    const leftTime = new Date(left.last_at || 0).getTime() || 0;
    const rightTime = new Date(right.last_at || 0).getTime() || 0;
    return rightTime - leftTime || left.slug.localeCompare(right.slug);
  });
}

function planResultAge(documentNode, value) {
  const age = relativeTimeNode(documentNode, value);
  const elapsed = Date.now() - new Date(value).getTime();
  if (
    Number.isFinite(elapsed)
    && elapsed >= 24 * 60 * 60 * 1000
    && elapsed < 48 * 60 * 60 * 1000
  ) {
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
  const table = el(documentNode, "table", "items qa-plans-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "Plan", "Project", "Target", "Cases", "Attached", "Last result",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of orderedPlans(rows)) {
    const href = qaRoute(
      context, "plans", String(row.id), row.project,
    );
    const tr = el(documentNode, "tr", "qa-clickable-row");
    tr.addEventListener("click", (event) => {
      if (event.target?.closest?.("a")) return;
      context.navigate(href);
    });
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
      target
        ? `${target.tenant.slug} · ${target.environment.name}`
        : "not bound",
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
      result.title = row.last_verdict_reason;
      result.appendChild(el(
        documentNode, "span", "qa-result-reason",
        ` · ${row.last_verdict_reason}`,
      ));
    }
    if (row.last_at && row.last_outcome === "passed") {
      result.appendChild(el(documentNode, "span", "qa-result-age", " "));
      result.appendChild(planResultAge(documentNode, row.last_at));
    }
    tr.appendChild(result);
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
    "authored in your harness — the web renders and steers",
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
