// The run's current checks, evidence, and human decision share one place on
// Shipping and on the run page. Earlier attempts remain in folded history.

import { evidenceStrip } from "./review_evidence_strip.js";
import { appendRunConclusion } from "./qa_run_conclusion.js";
import { evidenceOf } from "./review_request_presentation.js";
import { appendRunGates, gateAsRequest, runDecisionGates } from "./universe_run_gates.js";
import { effectiveRunChecks } from "./universe_run_evidence.js";
import { outcomeOf } from "./universe_run_verification.js";
import { el } from "./universe_view_support.js";

function uniqueEvidence(checks, gates) {
  const artifacts = [];
  const seen = new Set();
  const add = (artifact, requirementId) => {
    const id = String(artifact.id ?? artifact.artifact_id ?? "");
    if (id && seen.has(id)) return;
    if (id) seen.add(id);
    artifacts.push({ ...artifact, requirement_id: requirementId ?? artifact.requirement_id });
  };
  for (const gate of gates) {
    const evidence = evidenceOf(gateAsRequest(gate));
    for (const artifact of evidence.artifacts) add(artifact, evidence.requirementId);
  }
  for (const check of checks) {
    for (const artifact of check.artifacts || []) add(artifact, check.requirement_id);
  }
  return artifacts;
}

function checkLine(documentNode, check) {
  const line = el(documentNode, "div", "run-qa-check");
  line.appendChild(el(documentNode, "strong", null,
    [check.case_key, check.method_name].filter(Boolean).join(" · ") || "Check"));
  line.appendChild(el(documentNode, "span", null, outcomeOf(check)));
  if (check.verdict_reason) {
    const reason = el(documentNode, "details", "run-qa-reason");
    reason.appendChild(el(documentNode, "summary", null, "Details"));
    reason.appendChild(el(documentNode, "p", null, String(check.verdict_reason)));
    line.appendChild(reason);
  }
  if (!(check.artifacts || []).length) {
    appendRunConclusion(documentNode, line, check, "run-check-conclusion");
  }
  return line;
}

export function runQaSection(context, row, rawChecks, onAct, options = {}) {
  const documentNode = context.document;
  const runRows = (rawChecks || []).filter((check) => check.deployment_member_item_id == null);
  const checks = effectiveRunChecks(runRows);
  const drawn = options.drawnRequestIds || new Set();
  const gates = runDecisionGates(row).filter(
    (gate) => !drawn.has(String(gate.request_id)));
  const finalizing = row.current_stage === "complete" && row.status === "executing";
  if (!checks.length && !gates.length && !finalizing && !options.showEmpty) return null;
  const section = el(documentNode, "section", "run-qa-section");
  const head = el(documentNode, "div", "run-qa-head");
  head.appendChild(el(documentNode, options.headingTag || "h3", null, "Run QA"));
  if (checks.length) {
    const passed = checks.filter((check) => check.outcome === "passed").length;
    head.appendChild(el(documentNode, "span",
      `run-verdict ${passed === checks.length ? "is-approved" : "is-rejected"}`,
      `${passed} of ${checks.length} passed`));
  }
  section.appendChild(head);
  if (!checks.length && !gates.length) {
    section.appendChild(el(documentNode, "p", "run-copy", "No run checks were recorded."));
  }
  for (const check of checks) section.appendChild(checkLine(documentNode, check));
  const strip = evidenceStrip(context, uniqueEvidence(checks, gates), {
    compact: true, stepCaptionsOnly: true,
  });
  if (strip) section.appendChild(strip);
  appendRunGates(context, section, row, onAct, {
    drawnRequestIds: drawn, evidence: false,
  });
  const history = runRows.filter((check) => !checks.includes(check));
  if (history.length) {
    const details = el(documentNode, "details", "run-qa-history");
    details.appendChild(el(documentNode, "summary", null,
      `${history.length} earlier or superseded check${history.length === 1 ? "" : "s"}`));
    for (const check of history) {
      const line = checkLine(documentNode, check);
      const evidence = evidenceStrip(context, (check.artifacts || []).map(
        (artifact) => ({ ...artifact, requirement_id: check.requirement_id })),
      { compact: true, stepCaptionsOnly: true });
      if (evidence) line.appendChild(evidence);
      details.appendChild(line);
    }
    section.appendChild(details);
  }
  return section;
}
