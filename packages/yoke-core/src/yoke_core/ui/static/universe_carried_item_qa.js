// A run card draws only the carried item's checks bound to that run.
// Replaced and cancelled attempts remain in that run's folded history.

import { QA_KIND, QA_STATE, classifyQaRow } from "./qa_state.js";
import { effectiveChecks } from "./universe_run_evidence.js";

function newestFirst(rows) {
  return [...rows].sort((left, right) => (
    (Date.parse(right.happened_at || "") || 0) - (Date.parse(left.happened_at || "") || 0)
  ));
}

function answersForRun(row, rows) {
  const state = classifyQaRow(row, rows)?.id;
  return ![QA_STATE.CANCELLED, QA_STATE.SUPERSEDED, QA_STATE.WAIVED,
    QA_STATE.NO_OBLIGATION].includes(state);
}

export function itemQaChecks(rows, { runId } = {}) {
  const checks = (rows || []).filter((row) => row.deployment_run_id
    && String(row.deployment_run_id) === String(runId || "")
    && String(row.qa_kind || "") !== QA_KIND.STAGE_ACCEPTANCE);
  const current = effectiveChecks(checks.filter((row) => answersForRun(row, checks)));
  return {
    current,
    history: newestFirst(checks.filter((row) => !current.includes(row))),
  };
}

export const universeCarriedItemQa = { itemQaChecks };
