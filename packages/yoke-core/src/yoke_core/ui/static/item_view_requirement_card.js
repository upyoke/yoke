// One QA requirement as the reader of an item meets it: what was checked,
// how it came out, which revision it covers, and the evidence itself.
//
// The card used to BE a link to the method catalog, which made two problems
// at once. Its text could not be selected, so a reader could not copy a case
// key or a reason out of it; and following it landed on the method's contract
// and used-by plans rather than on the screenshots the verdict rests on. The
// evidence is drawn here through the same reader every other QA surface uses,
// and the method definition keeps its own link beside it.

import { attachTooltip } from "./universe_tooltip.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { artifactEvidenceCard } from "./qa_evidence_artifact_view.js";
import { el, statePill } from "./universe_view_support.js";

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
    attachTooltip(documentNode, pill, String(row.capture_degraded_reason));
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

// One requirement, and the evidence behind it — not a link to the contract
// its method is defined by. A card that reported "2 screenshots passed" and
// opened the method catalog showed the reader a definition and never the
// screenshots; the method definition is still one click away, as its own
// link, beside the evidence rather than instead of it.
function requirementEvidence(context, host, row) {
  const documentNode = context.document;
  const artifacts = Array.isArray(row.artifacts) ? row.artifacts : [];
  if (!artifacts.length) {
    if (row.run_id === null || row.run_id === undefined) return null;
    host.appendChild(el(
      documentNode,
      "div",
      "item-proof-evidence-none",
      "This run attached no artifacts.",
    ));
    return null;
  }
  const evidence = el(documentNode, "div", "item-proof-evidence");
  for (const artifact of artifacts) {
    evidence.appendChild(artifactEvidenceCard(context, artifact, row.id));
  }
  host.appendChild(evidence);
  return evidence;
}

function requirementLinks(documentNode, item, row) {
  const links = el(documentNode, "div", "item-proof-links");
  if (row.method_id) {
    const method = el(
      documentNode,
      "a",
      "item-proof-link-out",
      `${row.method_name || row.method_id} method →`,
    );
    method.href = buildUniverseRoute(
      "qa-methods", String(item.project.id), String(row.method_id),
    );
    links.appendChild(method);
  }
  const activity = el(
    documentNode, "a", "item-proof-link-out", "QA activity →",
  );
  activity.href = buildUniverseRoute("qa-activity", String(item.project.id));
  links.appendChild(activity);
  return links;
}

function requirementCard(context, item, row, workflowId) {
  const documentNode = context.document;
  const linked = ["blitz", "dash"].includes(workflowId);
  const card = el(documentNode, "div", "item-proof-row");
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
  copy.appendChild(el(
    documentNode,
    "div",
    "item-proof-subtitle",
    linked
      ? `${row.method_name || row.method_id || row.qa_kind} — ${proof}`
      : proof,
  ));
  // The revision the verdict covers, beside the verdict. Without it a passing
  // proof says nothing about whether it still describes the current tree.
  if (row.recorded_head_sha) {
    copy.appendChild(el(
      documentNode,
      "div",
      "item-proof-revision",
      `revision ${String(row.recorded_head_sha).slice(0, 12)}`,
    ));
  }
  requirementEvidence(context, copy, row);
  copy.appendChild(requirementLinks(documentNode, item, row));
  card.appendChild(copy);
  const pill = qaOutcomePill(documentNode, row, workflowId);
  if (pill) card.appendChild(pill);
  return card;
}


export const itemViewRequirementCard = {
  currentProof,
  qaOutcome,
  qaOutcomePill,
  requirementCard,
};
export { currentProof, qaOutcome, qaOutcomePill, requirementCard };
