import {
  el,
  statePill,
} from "./universe_view_support.js";
import {
  capabilityLabel,
  capabilityRoute,
  capabilityStateNode,
  detailHead,
  oneProjectCall,
  outcomeNode,
  projectCalls,
  qaPanel,
  showFailure,
  tableWrap,
} from "./qa_view_primitives.js";
import { reviewExplanation } from "./qa_review_explanation.js";
import { renderEvidence } from "./qa_view_evidence.js";
import { failureOutputNode } from "./qa_case_output_view.js";
import {
  waiverDialog,
} from "./qa_plan_actions.js";
import {
  executionTargetLabel,
  renderExecutionTarget,
} from "./qa_execution_target_view.js";

function evidenceCount(row) {
  const evidence = row.last_result.evidence || [];
  if (!evidence.length) return null;
  const screenshotCount = evidence.filter((artifact) =>
    String(artifact.content_type || "").startsWith("image/")
    || String(artifact.artifact_type || "").includes("screenshot")).length;
  if (screenshotCount) {
    return `${screenshotCount} ${
      screenshotCount === 1 ? "screenshot" : "screenshots"
    }`;
  }
  return `${evidence.length} ${
    evidence.length === 1 ? "artifact" : "artifacts"
  }`;
}

function proofLabel(row) {
  return row.last_result.host_baseline
    ? `${row.case_key} @${row.last_result.host_baseline}`
    : row.case_key;
}

function transitionId(row) {
  return String(row.transition_id || "unknown").toLowerCase();
}

function planProofRows(plan) {
  return plan.cases.flatMap((row) => {
    const proofs = row.proofs || (
      row.last_result ? [row.last_result] : []
    );
    return proofs.map((proof) => ({ ...row, last_result: proof }));
  });
}

function capabilityCell(context, row, project) {
  const documentNode = context.document;
  const capabilities = row.required_capabilities || [];
  if (!capabilities.length) {
    return el(documentNode, "span", "muted", "none");
  }
  const wrap = el(documentNode, "span", "qa-case-capability");
  for (const capability of capabilities) {
    const link = el(
      documentNode, "a", "qa-capability-link",
      capabilityLabel(capability.kind, capability.label),
    );
    link.href = capabilityRoute(context, project, capability.kind);
    wrap.appendChild(link);
    const pill = capabilityStateNode(
      documentNode, capability.context,
      capability.state || "not_configured", true,
    );
    if (pill) wrap.appendChild(pill);
  }
  return wrap;
}

function renderCases(context, plan, proofs, reload, overlayHost) {
  const documentNode = context.document;
  const countNote = !proofs.length
    ? "success policy: no cases declared"
    : proofs.length === plan.cases.length
    ? `success policy: all ${plan.cases.length} ${
      plan.cases.length === 1 ? "case passes" : "cases pass"
    }`
    : `success policy: all ${proofs.length} case-baseline proofs pass`;
  const result = qaPanel(
    documentNode,
    "Case sequence",
    plan.cases.length,
    countNote,
  );
  result.body.classList.add("qa-case-panel-body");
  if (!proofs.length) {
    result.body.appendChild(el(
      documentNode,
      "p",
      "empty qa-plan-empty",
      "No cases declared in this test plan yet.",
    ));
  } else {
    const table = el(documentNode, "table", "items qa-case-table");
    const head = el(documentNode, "tr");
    for (const label of [
      "#", "Case", "Method", "Capability", "Last result", "Actions",
    ]) {
      head.appendChild(el(documentNode, "th", null, label));
    }
    table.appendChild(head);
    for (const row of proofs) {
      const tr = el(documentNode, "tr");
      tr.appendChild(el(documentNode, "td", null, row.position));
      const caseCell = el(documentNode, "td", "mono", row.case_key);
      if (row.last_result.host_baseline) {
        caseCell.appendChild(el(
          documentNode,
          "span",
          "qa-host-baseline",
          ` @${row.last_result.host_baseline}`,
        ));
      }
      tr.appendChild(caseCell);
      tr.appendChild(el(documentNode, "td", null, row.method_name));
      const capability = el(documentNode, "td");
      capability.appendChild(capabilityCell(context, row, plan.project));
      tr.appendChild(capability);
      const outcome = el(documentNode, "td");
      outcome.appendChild(outcomeNode(
        documentNode,
        row.last_result.outcome,
        row.last_result.capture_degraded_reason,
        null,
        reviewExplanation(row.last_result.review),
      ));
      const count = evidenceCount(row);
      if (count) {
        outcome.appendChild(el(
          documentNode, "span", "qa-evidence-count", count,
        ));
      }
      const failureOutput = failureOutputNode(documentNode, row.last_result);
      if (failureOutput) outcome.appendChild(failureOutput);
      tr.appendChild(outcome);
      const actions = el(documentNode, "td", "qa-case-actions");
      if (
        row.last_result.requirement_id
        && row.last_result.run_id
        && row.last_result.outcome === "needs_review"
      ) {
        const actionRow = { ...row, case_key: proofLabel(row) };
        const waive = el(documentNode, "button", "btn", "Waive");
        waive.type = "button";
        waive.addEventListener("click", () => {
          const dialog = waiverDialog(context, actionRow, reload);
          overlayHost.appendChild(dialog);
        });
        actions.appendChild(waive);
      } else {
        actions.textContent = "—";
      }
      tr.appendChild(actions);
      table.appendChild(tr);
    }
    result.body.appendChild(tableWrap(documentNode, table));
  }
  const footer = el(documentNode, "div", "qa-union");
  footer.appendChild(statePill(
    documentNode,
    plan.union.satisfied ? "satisfied" : "not satisfied",
    plan.union.satisfied ? "union: satisfied" : "union: gate not satisfied",
  ));
  const counts = Object.entries(plan.union.counts)
    .map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`)
    .join(" · ");
  const gated = plan.attachments.find(
    (attachment) => attachment.kind === "project_default",
  );
  const waitSubject = gated
    ? `the ${transitionId(gated)} transition`
    : "the plan";
  footer.appendChild(el(
    documentNode, "span", null,
    `${counts || "no runs yet"} — ${waitSubject} waits until every case ` +
      "passes or is explicitly waived. Waive is a per-case engine action " +
      "on the materialized requirement, authority-checked at resolve.",
  ));
  result.body.appendChild(footer);
  const manage = el(documentNode, "div", "qa-panel-note");
  manage.appendChild(el(
    documentNode,
    "span",
    null,
    "Add, reorder, or retire cases — and change the success policy — from your harness: ",
  ));
  manage.appendChild(el(
    documentNode,
    "code",
    "qa-inline-command",
    `yoke qa plan edit ${plan.slug}`,
  ));
  result.root.appendChild(manage);
  return result.root;
}

function renderAttachments(documentNode, plan) {
  const result = qaPanel(
    documentNode,
    "Attached to",
    null,
    "project defaults · item attachments",
  );
  if (!plan.attachments.length) {
    result.body.appendChild(el(
      documentNode, "p", "empty", "not attached yet",
    ));
  }
  for (const row of plan.attachments) {
    const transition = transitionId(row);
    const card = el(documentNode, "div", "qa-attachment");
    const title = row.kind === "item"
      ? `${row.project} · ${row.item_ref || `item ${row.item_id}`}`
      : `${row.project} · project default`;
    card.appendChild(el(documentNode, "strong", null, title));
    card.appendChild(el(
      documentNode, "span", null,
      row.kind === "item"
        ? `${row.workflow_id} · ${transition}`
        : `gates the ${transition} transition for every ` +
          `${row.project} item`,
    ));
    result.body.appendChild(card);
  }
  return result.root;
}

function renderPlanDetail(context, host, plan, scope) {
  const documentNode = context.document;
  const reload = () => renderQaPlanDetail(
    context, host, scope, String(plan.id),
  );
  const proofs = planProofRows(plan);
  const grid = el(documentNode, "div", "qa-plan-detail-grid");
  const left = el(documentNode, "div", "qa-detail-stack");
  left.appendChild(renderCases(context, plan, proofs, reload, host));
  const right = el(documentNode, "div", "qa-detail-stack");
  right.appendChild(renderExecutionTarget(documentNode, plan));
  right.appendChild(renderAttachments(documentNode, plan));
  right.appendChild(renderEvidence(context, {
    ...plan,
    cases: proofs.map((row) => ({
      ...row,
      case_key: proofLabel(row),
    })),
  }));
  grid.appendChild(left);
  grid.appendChild(right);
  host.replaceChildren(
    detailHead(
      documentNode,
      plan.slug,
      `Test plan · ${plan.project} · ${executionTargetLabel(
        plan.execution_target,
      )}`,
    ),
    grid,
  );
}

async function planDetail(context, scope, planId) {
  const calls = projectCalls(
    context, scope, "qa.plan.get", { plan_id: Number(planId) },
  );
  const responses = await Promise.all(calls.map((call) => {
    const payload = { ...call.payload };
    const project = payload.project;
    delete payload.project;
    return oneProjectCall(context, call.functionId, project, payload);
  }));
  return {
    plan: responses.find(
      (result) => result.status === 200 && result.envelope.success,
    )?.envelope.result.plan,
    failure: responses.find((result) => !result.envelope?.success),
  };
}

export async function renderQaPlanDetail(
  context,
  main,
  scope,
  planId,
  navigation = {},
) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", `loading plan ${planId}…`,
  ));
  const detail = await planDetail(context, scope, planId);
  if (!context.isMounted()) return;
  if (!detail.plan) {
    showFailure(documentNode, main, detail.failure || {
      envelope: { error: { message: "QA plan not found." } },
    });
    return;
  }
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(detail.plan.slug || planId);
  }
  renderPlanDetail(context, main, detail.plan, scope);
}
