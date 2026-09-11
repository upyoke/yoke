import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeTime } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";
import { qaOutcome, requirementCard } from "./item_view_requirement_card.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { loadPendingReviews } from "./universe_run_evidence.js";
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

// A requirement whose review is still waiting on this reader points at the
// Inbox card that decides it. The item page does not carry that fact, so
// it is read once the rows are on screen and marked in place.
function markPendingReviews(context, body, item) {
  if (!context.client || !item.project?.id) return;
  loadPendingReviews(context, [item.project.id]).then((pending) => {
    if (!pending.size || (typeof context.isMounted === "function" && !context.isMounted())) return;
    for (const card of Array.from(body.children)) {
      const request = pending.get(String(card.getAttribute?.("data-requirement-id")));
      if (!request) continue;
      const copy = Array.from(card.children).find(
        (child) => child.classList.contains("item-proof-copy"),
      );
      const link = el(context.document, "a", "review-pill is-pending", "needs your review →");
      link.href = buildUniverseRoute("inbox", String(item.project.id));
      (copy || card).appendChild(link);
    }
  });
}

export function verificationPanel(context, item) {
  const documentNode = context.document;
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
      body.appendChild(requirementCard(context, item, row, workflowId));
    }
  }
  for (const row of rows) {
    if (renderedRows.has(row.id)) continue;
    renderedRows.add(row.id);
    body.appendChild(requirementCard(context, item, row, workflowId));
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
  markPendingReviews(context, body, item);
  return panel;
}
