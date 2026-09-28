// Which of a carried item's checks answer for the run on screen.
//
// An item's current checks are the latest live attempt of each member check
// this run recorded for it; failing those, the one check that ran against
// the revision this run deployed. Every other check the item has — before
// merge, earlier releases, superseded or waived attempts — is its history,
// newest first, drawn in the same "Earlier checks" disclosure a run uses.

import {
  QA_KIND,
  QA_STATE,
  classifyQaRow,
  ranAgainstDeployedRevision,
} from "./qa_state.js";
import { effectiveChecks } from "./universe_run_evidence.js";
import { isBeforeMergeCheck } from "./universe_run_qa_checks.js";

function isRunMachinery(row) {
  return String(row?.qa_kind || "") === QA_KIND.STAGE_ACCEPTANCE;
}

function newestFirst(rows) {
  return [...rows].sort((left, right) => (
    (Date.parse(right.happened_at || "") || 0) - (Date.parse(left.happened_at || "") || 0)
  ));
}

function recordedOn(row, runId) {
  return Boolean(row.deployment_run_id)
    && String(row.deployment_run_id) === String(runId || "");
}

// A superseded, waived or no-obligation row answers for nothing; it stays in
// the item's history rather than counting as a current check.
function answersForRun(row, rows) {
  const state = classifyQaRow(row, rows)?.id;
  return ![QA_STATE.SUPERSEDED, QA_STATE.WAIVED, QA_STATE.NO_OBLIGATION].includes(state);
}

// The check that answers for the revision this run deployed: one whose
// observed lineage is the deployed revision, or one this very run recorded.
// A passing one is preferred over a newer failure it already answered.
export function deployedRevisionCheck(rows, { runId, deployedSha } = {}) {
  const candidates = newestFirst(rows).filter((row) => {
    if (isBeforeMergeCheck(row) || !answersForRun(row, rows)) return false;
    return ranAgainstDeployedRevision(row, deployedSha) || recordedOn(row, runId);
  });
  return candidates.find((row) => String(row.outcome || "") === "passed")
    || candidates[0] || null;
}

// `options`: runId, deployedSha. Returns `{ current, history }`.
export function itemQaChecks(rows, options = {}) {
  const checks = (rows || []).filter((row) => !isRunMachinery(row));
  let current = effectiveChecks(checks.filter(
    (row) => recordedOn(row, options.runId) && answersForRun(row, checks)));
  if (!current.length) {
    const lead = deployedRevisionCheck(checks, options);
    current = lead ? [lead] : [];
  }
  return {
    current,
    history: newestFirst(checks.filter((row) => !current.includes(row))),
  };
}

export const universeCarriedItemQa = {
  deployedRevisionCheck,
  itemQaChecks,
};
