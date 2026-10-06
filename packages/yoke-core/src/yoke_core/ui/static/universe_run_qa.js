// The run's own checks, their evidence, and the human decisions share one
// "Run QA" section on Shipping and on the run page, below every carried
// item. A carried item's checks and decisions sit in that item's own "Item
// QA" section instead, drawn by the same components.

import { appendRunGates, runDecisionGates, runFinalizationNote } from "./universe_run_gates.js";
import { effectiveRunChecks } from "./universe_run_evidence.js";
import {
  drawnCheckArtifactIds,
  qaScopeSection,
  runHumanDecision,
} from "./universe_run_qa_checks.js";

// Returns the Run QA section, or — for a run with no checks and no decision —
// only the finalization note when the run is settling, or nothing at all.
// ``options.drawnRequestIds`` names the decisions a carried item already drew.
export function runQaSection(context, row, rawChecks, onAct, options = {}) {
  const runRows = (rawChecks || []).filter((check) => check.deployment_member_public_ref == null);
  const checks = effectiveRunChecks(runRows);
  const drawn = options.drawnRequestIds || new Set();
  const gates = runDecisionGates(row).filter(
    (gate) => !drawn.has(String(gate.request_id)));
  if (!checks.length && !gates.length) return runFinalizationNote(context.document, row);
  const section = qaScopeSection(context, {
    heading: "Run QA",
    headingTag: options.headingTag,
    current: checks,
    history: runRows.filter((check) => !checks.includes(check)),
    decision: runHumanDecision(gates.filter((gate) => gate.kind === "qa_needs_review")),
    runId: row.id,
    project: row.project_id,
  });
  appendRunGates(context, section, row, onAct, {
    drawnRequestIds: drawn, drawnArtifactIds: drawnCheckArtifactIds(runRows),
  });
  return section;
}
