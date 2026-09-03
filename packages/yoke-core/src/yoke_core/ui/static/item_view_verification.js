import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeTime } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";
import { workflowPanel } from "./workflow_view_primitives.js";
function qaOutcome(row) {
  if (row.waived_at) return "waived";
  const outcome = String(
    row.outcome ||
    row.case_outcome ||
    row.verdict ||
    row.execution_status ||
    "queued",
  ).toLowerCase().replaceAll("_", " ");
  if (outcome === "pass") return "passed";
  if (["fail", "error"].includes(outcome)) return "failed";
  if (outcome === "undetermined") return "needs review";
  return outcome;
}
function qaOutcomePill(documentNode, row, workflowId) {
  const outcome = qaOutcome(row);
  let label = workflowId === "dash" && outcome === "needs review"
    ? "review"
    : outcome;
  if (row.capture_degraded_reason && outcome === "passed") {
    label = "passed · degraded";
  }
  const pill = statePill(documentNode, outcome, label);
  if (pill && row.capture_degraded_reason) {
    pill.title = String(row.capture_degraded_reason);
  }
  return pill;
}
function currentProof(row) {
  let summary = String(row.proof_summary || "").trim();
  if (!summary) {
    summary = [
      row.lease_summary,
      row.evidence_summary,
    ].map((part) => String(part || "").trim()).filter(Boolean).join(" · ");
  }
  const degradedReason = String(row.capture_degraded_reason || "").trim();
  if (degradedReason) {
    const sharedSummary = `text capture + reason — ${degradedReason}`;
    if (summary === sharedSummary) {
      summary = `text capture + reason; ${degradedReason}`;
    } else if (!summary.includes(degradedReason)) {
      summary = summary
        ? `${summary}; ${degradedReason}`
        : `capture degraded; ${degradedReason}`;
    }
  }
  if (summary) return summary;
  if (row.run_id === null || row.run_id === undefined) return "not run";
  if (qaOutcome(row) === "blocked on precondition") {
    const baseline = String(row.host_baseline || "precondition")
      .replaceAll("_", " ");
    const reason = String(row.precondition_reason || "blocked")
      .replaceAll("_", " ");
    return `baseline ${baseline} ${reason} — case did not run`;
  }
  return "run recorded";
}
function derivedPlanAttachments(rows) {
  const plans = new Map();
  for (const row of rows) {
    if (!row.plan_id) continue;
    const transition = row.workflow_transition_id ||
      row.qa_phase ||
      "verification";
    const key = `${row.plan_id}:${transition}`;
    const attachment = plans.get(key) || {
      plan_id: row.plan_id,
      plan_slug: row.plan_slug,
      plan_name: row.plan_name,
      transition_id: transition,
      source: "materialized requirement",
      materialized_at: row.created_at,
      materialized_count: 0,
    };
    attachment.materialized_count += 1;
    plans.set(key, attachment);
  }
  return [...plans.values()];
}
function planCard(documentNode, item, attachment, workflowId) {
  const plan = el(documentNode, "a", "item-proof-plan");
  plan.href = buildUniverseRoute(
    "qa-plans",
    String(item.project.id),
    attachment.plan_id ? String(attachment.plan_id) : null,
  );
  plan.appendChild(el(documentNode, "span", "item-proof-icon", "⌥"));
  const copy = el(documentNode, "span", "item-proof-copy");
  const title = attachment.plan_slug ||
    attachment.plan_name ||
    `Plan ${attachment.plan_id}`;
  copy.appendChild(el(
    documentNode,
    "strong",
    "item-proof-title",
    `${title} → ${attachment.transition_id || attachment.qa_phase}`,
  ));
  const subtitle = el(documentNode, "span", "item-proof-subtitle");
  subtitle.appendChild(el(
    documentNode,
    "span",
    null,
    `${attachment.source || "attached plan"} · `,
  ));
  if (workflowId === "epic") {
    const transition = attachment.transition_id || attachment.qa_phase;
    subtitle.replaceChildren(el(
      documentNode,
      "span",
      null,
      transition === "release"
        ? `${attachment.source || "attached plan"} · materializes one ` +
          `requirement per case at ${transition}`
        : `${attachment.source || "attached plan"} · plus per-task ` +
          "attachments · materializes per case",
    ));
  } else if (Number(attachment.materialized_count)) {
    subtitle.appendChild(el(documentNode, "span", null, "materialized "));
    if (attachment.materialized_at) {
      subtitle.appendChild(relativeTime(documentNode, attachment.materialized_at));
    } else {
      subtitle.appendChild(el(documentNode, "span", null, "for this item"));
    }
    subtitle.appendChild(el(
      documentNode,
      "span",
      null,
      " — one requirement per case",
    ));
  } else {
    subtitle.appendChild(el(
      documentNode,
      "span",
      null,
      `not materialized yet — expands one requirement per case at ${
        attachment.transition_id || "the attached transition"
      }`,
    ));
  }
  copy.appendChild(subtitle);
  plan.appendChild(copy);
  plan.appendChild(el(documentNode, "span", "item-proof-arrow", "plan →"));
  return plan;
}
function proofMethodIcon(row) {
  const method = String(
    row.method_id || row.method_name || row.qa_kind || "",
  ).toLowerCase();
  if (method.includes("terminal") && method.includes("inspection")) return "⌘";
  if (method.includes("terminal")) return "⌨";
  if (method.includes("machine") && method.includes("state")) return "≡";
  if (method.includes("browser") && method.includes("inspection")) return "◎";
  if (method.includes("browser")) return "◉";
  if (method.includes("command")) return "⌥";
  return "✓";
}

function requirementCard(documentNode, item, row, workflowId) {
  const linked = ["blitz", "dash"].includes(workflowId);
  const card = el(
    documentNode,
    "a",
    `item-proof-row${linked ? " item-proof-link" : ""}`,
  );
  card.href = linked && row.method_id
    ? buildUniverseRoute(
      "qa-methods", String(item.project.id), String(row.method_id),
    )
    : buildUniverseRoute("qa-activity", String(item.project.id));
  if (linked) {
    card.appendChild(el(
      documentNode, "span", "item-proof-icon", proofMethodIcon(row),
    ));
  }
  const copy = el(documentNode, "div", "item-proof-copy");
  const heading = el(documentNode, "div", "item-proof-heading");
  const title = workflowId === "dash"
    ? `ad hoc · ${row.requirement_source || row.plan_case_key || row.qa_kind}`
    : workflowId === "blitz"
      ? `${row.plan_slug || row.plan_name || "verification"} · ${
        row.plan_case_key || row.requirement_source || row.qa_kind
      }`
      : row.plan_case_key ||
        row.requirement_source ||
        row.method_name ||
        row.qa_kind ||
        `requirement ${row.id}`;
  heading.appendChild(el(
    documentNode,
    "span",
    `item-proof-title${linked ? "" : " mono"}`,
    title,
  ));
  if (!linked) {
    heading.appendChild(el(
      documentNode,
      "span",
      "item-method-badge",
      row.method_name || row.method_id || row.qa_kind,
    ));
  }
  copy.appendChild(heading);
  const proof = currentProof(row);
  const subtitle = linked
    ? `${row.method_name || row.method_id || row.qa_kind} — ${proof}`
    : proof;
  copy.appendChild(el(
    documentNode,
    "div",
    "item-proof-subtitle",
    subtitle,
  ));
  card.appendChild(copy);
  const pill = qaOutcomePill(documentNode, row, workflowId);
  if (pill) card.appendChild(pill);
  return card;
}

function unionCard(documentNode, rows) {
  const outcomes = rows.map(qaOutcome);
  const unsatisfied = outcomes.filter(
    (value) => !["pass", "passed", "waived", "succeeded"].includes(
      String(value).toLowerCase(),
    ),
  ).length;
  const counts = new Map();
  for (const outcome of outcomes) {
    counts.set(outcome, Number(counts.get(outcome) || 0) + 1);
  }
  const transitions = [...new Set(rows.map(
    (row) => row.workflow_transition_id,
  ).filter(Boolean))];
  const transition = transitions.length === 1
    ? transitions[0]
    : "the transition";
  const union = el(documentNode, "div", "item-proof-union");
  const copy = el(documentNode, "span", "item-proof-copy");
  copy.appendChild(el(
    documentNode,
    "strong",
    null,
    "Union verdict — the gate reflects it",
  ));
  copy.appendChild(el(
    documentNode,
    "span",
    "item-muted",
    `${[...counts.entries()].map(
      ([outcome, count]) => `${count} ${outcome}`,
    ).join(" · ")}; ${transition} waits until every case passes or is waived`,
  ));
  union.appendChild(copy);
  const verdict = unsatisfied ? "not satisfied yet" : "satisfied";
  const pill = statePill(documentNode, verdict);
  if (pill) union.appendChild(pill);
  return union;
}

export function verificationPanel(documentNode, item) {
  const rows = item.qa_requirements || [];
  const workflowId = String(item.workflow.id || "").toLowerCase();
  const recordedAttachments = item.qa_plan_attachments || [];
  const recordedKeys = new Set(recordedAttachments.map(
    (attachment) => `${attachment.plan_id}:${
      attachment.transition_id || attachment.qa_phase || "verification"
    }`,
  ));
  const attachments = [
    ...recordedAttachments,
    ...derivedPlanAttachments(rows).filter(
      (attachment) => !recordedKeys.has(
        `${attachment.plan_id}:${attachment.transition_id}`,
      ),
    ),
  ];
  const { panel, body } = workflowPanel(
    documentNode,
    "Verification",
    workflowId === "issue"
      ? { detail: "is this item proven? one place" }
      : {},
  );
  body.className += " item-stack";
  if (
    !rows.length &&
    (!attachments.length || workflowId === "blitz")
  ) {
    body.appendChild(el(
      documentNode,
      "p",
      "empty",
      "No verification plans or item-scoped requirements are attached.",
    ));
    return panel;
  }

  const renderedRows = new Set();
  const materialized = attachments.filter(
    (attachment) => Number(attachment.materialized_count),
  );
  const pending = attachments.filter(
    (attachment) => !Number(attachment.materialized_count),
  );
  for (const attachment of materialized) {
    if (workflowId !== "blitz") {
      body.appendChild(planCard(
        documentNode, item, attachment, workflowId,
      ));
    }
    for (const row of rows) {
      if (renderedRows.has(row.id) || row.plan_id !== attachment.plan_id) {
        continue;
      }
      if (
        row.workflow_transition_id &&
        attachment.transition_id &&
        row.workflow_transition_id !== attachment.transition_id
      ) continue;
      renderedRows.add(row.id);
      body.appendChild(requirementCard(
        documentNode, item, row, workflowId,
      ));
    }
  }
  for (const row of rows) {
    if (renderedRows.has(row.id)) continue;
    renderedRows.add(row.id);
    body.appendChild(requirementCard(documentNode, item, row, workflowId));
  }
  if (rows.length && workflowId === "issue") {
    body.appendChild(unionCard(documentNode, rows));
  }
  for (const attachment of pending) {
    if (workflowId !== "blitz") {
      body.appendChild(planCard(
        documentNode, item, attachment, workflowId,
      ));
    }
  }
  return panel;
}
