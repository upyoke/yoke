// The run's own checks, the checks of plans several carried items share,
// their evidence, and the human decisions share one "Run QA" section on
// Shipping and on the run page, below every carried item. A carried item's
// own checks and decisions sit in that item's "Item QA" section instead,
// drawn by the same components.

import { appendRunGates, runDecisionGates, runFinalizationNote } from "./universe_run_gates.js";
import { effectiveRunChecks } from "./universe_run_evidence.js";
import {
  drawnCheckArtifactIds,
  qaScopeSection,
  runHumanDecision,
} from "./universe_run_qa_checks.js";
import { groupRunChecks } from "./run_qa_sharing.js";

// Returns the Run QA section, or — for a run with no checks and no decision —
// only the finalization note when the run is settling, or nothing at all.
// ``options.drawnRequestIds`` names the decisions a carried item already drew;
// ``options.sharing`` is the run's plan groups, whose checks are drawn here
// once under their sharing items' label.
export function runQaSection(context, row, rawChecks, onAct, options = {}) {
  const runRows = (rawChecks || []).filter((check) => check.deployment_member_public_ref == null);
  const checks = effectiveRunChecks(runRows);
  const { own, groups } = groupRunChecks(checks, options.sharing);
  const drawn = options.drawnRequestIds || new Set();
  const gates = runDecisionGates(row).filter(
    (gate) => !drawn.has(String(gate.request_id)));
  if (!checks.length && !groups.length && !gates.length) {
    return runFinalizationNote(context.document, row);
  }
  const section = qaScopeSection(context, {
    heading: "Run QA",
    headingTag: options.headingTag,
    current: own,
    groups,
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
