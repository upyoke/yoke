import { el } from "./universe_view_support.js";
import {
  capabilityLabel,
  detailHead,
  loadProjectCalls,
  methodIcon,
  oneProjectCall,
  outcomeNode,
  qaPanel,
  showFailure,
} from "./qa_view_primitives.js";
import { renderEvidence } from "./qa_view_evidence.js";

function attachmentText(attachments) {
  if (!attachments?.length) return "not attached";
  return attachments.map((row) => {
    if (row.kind === "item") {
      return `item · ${row.item_id} · ${row.transition_id}`;
    }
    return `project default · ${row.transition_id}`;
  }).join(" · ");
}

function methodSummary(documentNode, row) {
  const wrap = el(documentNode, "span", "qa-method-summary");
  wrap.appendChild(el(
    documentNode, "strong", null, String(row.case_count),
  ));
  for (const methodId of row.method_ids || []) {
    const icon = el(
      documentNode, "span", "qa-method-glyph", methodIcon(methodId),
    );
    icon.title = methodId;
    wrap.appendChild(icon);
  }
  if (Number(row.materialized_requirement_count) > Number(row.case_count)) {
    wrap.appendChild(el(
      documentNode, "span", "qa-baseline-count",
      `${row.materialized_requirement_count} reqs × baseline`,
    ));
  }
  return wrap;
}

function renderPlanTable(documentNode, body, rows, open) {
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
    "Plan", "Project", "Cases", "Attached", "Last result",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    const planCell = el(documentNode, "td");
    const button = el(documentNode, "button", "qa-plan-button", row.slug);
    button.type = "button";
    button.addEventListener("click", () => open(row));
    planCell.appendChild(button);
    tr.appendChild(planCell);
    tr.appendChild(el(documentNode, "td", null, row.project));
    const methods = el(documentNode, "td");
    methods.appendChild(methodSummary(documentNode, row));
    tr.appendChild(methods);
    tr.appendChild(el(
      documentNode, "td", null, attachmentText(row.attachments),
    ));
    const result = el(documentNode, "td");
    result.appendChild(outcomeNode(
      documentNode, row.last_outcome || "not run",
    ));
    tr.appendChild(result);
    table.appendChild(tr);
  }
  body.appendChild(table);
}

function renderCases(documentNode, plan) {
  const result = qaPanel(
    documentNode, "Case sequence", plan.cases.length,
  );
  const table = el(documentNode, "table", "items qa-case-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "#", "Case", "Method", "Capability", "Last result", "Actions",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const row of plan.cases) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", null, row.position));
    tr.appendChild(el(documentNode, "td", "mono", row.case_key));
    tr.appendChild(el(documentNode, "td", null, row.method_name));
    tr.appendChild(el(
      documentNode, "td", null,
      capabilityLabel(row.required_capability_kind),
    ));
    const outcome = el(documentNode, "td");
    outcome.appendChild(outcomeNode(
      documentNode,
      row.last_result.outcome,
      row.last_result.capture_degraded_reason,
    ));
    tr.appendChild(outcome);
    const actions = el(documentNode, "td", "qa-case-actions");
    if (row.last_result.requirement_id) {
      const rerun = el(documentNode, "button", "btn", "Rerun");
      rerun.type = "button";
      rerun.disabled = true;
      rerun.title = "Executor steering is not available from this browser.";
      actions.appendChild(rerun);
      if (!["passed", "waived"].includes(row.last_result.outcome)) {
        const waive = el(documentNode, "button", "btn", "Waive");
        waive.type = "button";
        waive.disabled = true;
        waive.title = "Waiver steering requires an item claim.";
        actions.appendChild(waive);
      }
    } else {
      actions.textContent = "—";
    }
    tr.appendChild(actions);
    table.appendChild(tr);
  }
  result.body.appendChild(table);
  const footer = el(documentNode, "div", "qa-union");
  footer.appendChild(outcomeNode(
    documentNode,
    plan.union.satisfied ? "union satisfied" : "union gate not satisfied",
  ));
  const counts = Object.entries(plan.union.counts)
    .map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`)
    .join(" · ");
  footer.appendChild(el(
    documentNode, "span", null,
    `${counts || "no runs yet"} — every case must pass or be waived.`,
  ));
  result.body.appendChild(footer);
  return result.root;
}

function renderAttachments(documentNode, plan) {
  const result = qaPanel(documentNode, "Attached to");
  if (!plan.attachments.length) {
    result.body.appendChild(el(
      documentNode, "p", "empty", "not attached yet",
    ));
  }
  for (const row of plan.attachments) {
    const card = el(documentNode, "div", "qa-attachment");
    const title = row.kind === "item"
      ? `${row.project} · item ${row.item_id}`
      : `${row.project} · project default`;
    card.appendChild(el(documentNode, "strong", null, title));
    card.appendChild(el(
      documentNode, "span", null,
      `${row.workflow_id} · ${row.transition_id}`,
    ));
    result.body.appendChild(card);
  }
  return result.root;
}

function renderPlanDetail(context, host, plan, back) {
  const documentNode = context.document;
  const grid = el(documentNode, "div", "qa-plan-detail-grid");
  const left = el(documentNode, "div", "qa-detail-stack");
  left.appendChild(renderCases(documentNode, plan));
  const command = qaPanel(documentNode, "Manage from your harness");
  command.body.appendChild(el(
    documentNode, "code", "qa-command",
    `yoke qa plan-cases replace --project ${plan.project} ` +
    `--plan-id ${plan.id} --stdin`,
  ));
  command.body.appendChild(el(
    documentNode, "p", null,
    "Add, reorder, or retire cases and change the declared success policy.",
  ));
  left.appendChild(command.root);
  const right = el(documentNode, "div", "qa-detail-stack");
  right.appendChild(renderAttachments(documentNode, plan));
  right.appendChild(renderEvidence(context, plan));
  grid.appendChild(left);
  grid.appendChild(right);
  host.replaceChildren(
    detailHead(
      documentNode,
      plan.name,
      `Test plan · ${plan.project} · success policy: ${
        plan.success_policy_id
      }`,
      back,
    ),
    grid,
  );
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
  const showList = () => {
    const result = qaPanel(documentNode, "Test plans", rows.length);
    renderPlanTable(documentNode, result.body, rows, async (row) => {
      main.replaceChildren(el(
        documentNode, "p", "empty", `loading ${row.slug}…`,
      ));
      const detail = await oneProjectCall(
        context,
        "qa.plan.get",
        row.project,
        { plan_id: row.id },
      );
      if (!context.isMounted()) return;
      if (detail.status !== 200 || !detail.envelope.success) {
        showFailure(documentNode, main, detail);
        return;
      }
      renderPlanDetail(
        context,
        main,
        detail.envelope.result.plan,
        showList,
      );
    });
    const note = el(documentNode, "div", "qa-panel-note");
    note.textContent =
      "Plans and ordered cases are authored through registered harness surfaces.";
    result.root.appendChild(note);
    main.replaceChildren(result.root);
  };
  showList();
}
