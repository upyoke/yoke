// The run's current checks, their evidence, and the human decision share one
// place on Shipping and on the run page. Each screenshot sits under the check
// that captured it; earlier attempts stay folded above the decision.

import { appendRunGates, runDecisionGates, runFinalizationNote } from "./universe_run_gates.js";
import { effectiveRunChecks } from "./universe_run_evidence.js";
import {
  appendRunChecks,
  runHumanDecision,
  runQaVerdict,
} from "./universe_run_qa_checks.js";
import { el } from "./universe_view_support.js";

// Returns the Run QA section, or — for a run with no checks and no decision —
// only the finalization note when the run is settling, or nothing at all.
export function runQaSection(context, row, rawChecks, onAct, options = {}) {
  const documentNode = context.document;
  const runRows = (rawChecks || []).filter((check) => check.deployment_member_item_id == null);
  const checks = effectiveRunChecks(runRows);
  const drawn = options.drawnRequestIds || new Set();
  const gates = runDecisionGates(row).filter(
    (gate) => !drawn.has(String(gate.request_id)));
  if (!checks.length && !gates.length) return runFinalizationNote(documentNode, row);
  const decision = runHumanDecision(gates);
  const section = el(documentNode, "section", "run-qa-section");
  const head = el(documentNode, "div", "run-qa-head");
  head.appendChild(el(documentNode, options.headingTag || "h3", null, "Run QA"));
  if (checks.length) {
    const verdict = runQaVerdict(checks, decision);
    head.appendChild(el(documentNode, "span", `run-verdict ${verdict.tone}`, verdict.text));
  }
  section.appendChild(head);
  const history = runRows.filter((check) => !checks.includes(check));
  appendRunChecks(context, section, checks, history, decision);
  const drawnArtifactIds = new Set(runRows.flatMap((check) => (check.artifacts || [])
    .map((artifact) => String(artifact.id ?? artifact.artifact_id ?? ""))));
  appendRunGates(context, section, row, onAct, { drawnRequestIds: drawn, drawnArtifactIds });
  return section;
}
