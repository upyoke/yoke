// Closed vocabulary for QA facts a release actually records. Every screen
// that draws QA state reads this, so waived / no-obligation / never-asked
// / standing-source / admitted-copy cannot collapse into "nothing" or into
// each other. Not a general QA framework: these states, then stop.

import { el, statePill } from "./universe_view_support.js";

export const QA_KIND = Object.freeze({
  STAGE_ACCEPTANCE: "deployment_stage_acceptance",
  NO_OBLIGATION: "post_deploy_no_obligation",
  NOT_REQUIRED: "post_deploy_not_required",
});

export const QA_STATE = Object.freeze({
  VERIFIED_RUN: "verified_run",
  VERIFIED_ITEM: "verified_item",
  STANDING_SOURCE: "standing_source",
  ADMITTED_COPY: "admitted_copy",
  SUPERSEDED: "superseded",
  WAIVED: "waived",
  NO_OBLIGATION: "no_obligation",
  NEVER_ASKED: "never_asked",
  RUN_MACHINERY: "run_machinery",
  FAILED: "failed",
  QUEUED: "queued",
  NEEDS_REVIEW: "needs_review",
});

const ADMITTED = /^admitted-requirement-(\d+)$/;

export function observedReleaseLineage(row) {
  const raw = row?.execution_target_json;
  let target = raw;
  if (typeof raw === "string") {
    try { target = JSON.parse(raw); } catch { return ""; }
  }
  if (!target || typeof target !== "object") return "";
  return String(target.observation?.observed_release_lineage
    || target.deployment?.release_lineage || "").trim();
}

export function ranAgainstDeployedRevision(row, deployedSha) {
  const observed = observedReleaseLineage(row);
  const deployed = String(deployedSha || "").trim();
  return Boolean(observed && deployed && observed === deployed);
}

const LABELS = Object.freeze({
  [QA_STATE.VERIFIED_RUN]: "verified this release",
  [QA_STATE.VERIFIED_ITEM]: "verified before merge",
  [QA_STATE.STANDING_SOURCE]: "source requirement",
  [QA_STATE.ADMITTED_COPY]: "this release",
  [QA_STATE.SUPERSEDED]: "superseded",
  [QA_STATE.WAIVED]: "waived",
  [QA_STATE.NO_OBLIGATION]: "no obligation",
  [QA_STATE.NEVER_ASKED]: "never asked",
  [QA_STATE.RUN_MACHINERY]: "run gate",
  [QA_STATE.FAILED]: "failed",
  [QA_STATE.QUEUED]: "queued",
  [QA_STATE.NEEDS_REVIEW]: "needs review",
});
const PILL = LABELS;

function kindOf(row) {
  return String(row?.qa_kind || "");
}

function phaseOf(row) {
  return String(row?.qa_phase || "");
}

function caseKey(row) {
  return String(row?.plan_case_key || row?.case_key || "");
}

function outcomeOf(row) {
  return String(row?.outcome || row?.case_outcome || row?.verdict || "")
    .toLowerCase()
    .replaceAll("_", " ");
}

function passed(row) {
  const outcome = outcomeOf(row);
  return outcome === "passed" || outcome === "pass" || outcome === "succeeded";
}

function reasonOf(row) {
  return String(
    row?.waiver_rationale
    || row?.instructions
    || row?.supersession_rationale
    || row?.proof_summary
    || "",
  ).trim();
}

export function admittedSourceId(row) {
  const match = ADMITTED.exec(caseKey(row));
  return match ? Number(match[1]) : null;
}

function isStageAcceptance(row) {
  return kindOf(row) === QA_KIND.STAGE_ACCEPTANCE;
}

function isPreMergeVerification(row) {
  return phaseOf(row) === "verification" && !row?.deployment_run_id;
}

export function isPostDeployFact(row) {
  if (!row || isStageAcceptance(row) || isPreMergeVerification(row)) return false;
  const kind = kindOf(row);
  if (kind === QA_KIND.NO_OBLIGATION || kind === QA_KIND.NOT_REQUIRED) return true;
  if (phaseOf(row) === "post_deploy") return true;
  return Boolean(row.deployment_run_id);
}

function state(id, detail = "") {
  return { id, label: LABELS[id], pill: PILL[id], detail };
}

export function classifyQaRow(row, rows = []) {
  if (!row) return null;
  if (isStageAcceptance(row)) {
    return state(
      QA_STATE.RUN_MACHINERY,
      "Stage acceptance is the run's own gate, not this item's check.",
    );
  }
  if (kindOf(row) === QA_KIND.NO_OBLIGATION) {
    return state(
      QA_STATE.NO_OBLIGATION,
      reasonOf(row) || "Nothing about this item is observable once deployed.",
    );
  }
  if (kindOf(row) === QA_KIND.NOT_REQUIRED || row.waived_at) {
    return state(
      QA_STATE.WAIVED,
      reasonOf(row) || "An obligation existed and was declined.",
    );
  }
  if (row.superseded_by_requirement_id || row.superseded_at) {
    return state(
      QA_STATE.SUPERSEDED,
      reasonOf(row) || "Replaced by a corrected case that actually ran.",
    );
  }
  const sourceId = admittedSourceId(row);
  if (sourceId != null) {
    return state(
      QA_STATE.ADMITTED_COPY,
      `Admitted copy of source requirement ${sourceId}; this is what ran for this release.`,
    );
  }
  const id = Number(row.id ?? row.requirement_id);
  const hasCopy = (rows || []).some(
    (other) => admittedSourceId(other) === id,
  );
  if (
    row.item_id != null
    && !row.deployment_run_id
    && phaseOf(row) === "post_deploy"
    && hasCopy
  ) {
    return state(
      QA_STATE.STANDING_SOURCE,
      "Stays open so the next release admits the same body. Open is expected.",
    );
  }
  if (isPreMergeVerification(row) && passed(row)) {
    return state(QA_STATE.VERIFIED_ITEM);
  }
  if (row.deployment_run_id && passed(row)) {
    return state(QA_STATE.VERIFIED_RUN);
  }
  if (row.item_id != null && !row.deployment_run_id && phaseOf(row) === "post_deploy") {
    return state(
      QA_STATE.STANDING_SOURCE,
      hasCopy
        ? "Stays open so the next release admits the same body. Open is expected."
        : "Intake source. Open until a release admits a copy and runs it.",
    );
  }
  if (!isPostDeployFact(row) && !row.deployment_run_id) return null;
  const outcome = outcomeOf(row);
  if (outcome === "failed" || outcome === "fail" || outcome === "error") {
    return state(QA_STATE.FAILED);
  }
  if (outcome === "undetermined" || outcome === "needs review") {
    return state(QA_STATE.NEEDS_REVIEW);
  }
  return state(QA_STATE.QUEUED);
}

function hasState(entries, id) {
  return entries.some((entry) => entry.state.id === id);
}

export function classifyMemberQa(rows, { runId } = {}) {
  const wanted = String(runId || "");
  const facts = (rows || []).filter((row) => {
    if (!isPostDeployFact(row)) return false;
    const recorded = String(row.deployment_run_id || "");
    return !recorded || recorded === wanted;
  });
  const entries = facts
    .map((row) => ({ row, state: classifyQaRow(row, rows) }))
    .filter((entry) => entry.state);
  const waived = entries.find((entry) => entry.state.id === QA_STATE.WAIVED);
  if (waived) return { ...waived.state, rows: facts };
  const none = entries.find((entry) => entry.state.id === QA_STATE.NO_OBLIGATION);
  if (none) return { ...none.state, rows: facts };
  const verified = entries.filter((entry) => (
    entry.state.id === QA_STATE.VERIFIED_RUN
    || entry.state.id === QA_STATE.ADMITTED_COPY
  ) && passed(entry.row));
  if (verified.length) {
    const failed = facts.filter((row) => {
      const classified = classifyQaRow(row, rows);
      return classified?.id === QA_STATE.FAILED;
    }).length;
    const passedCount = verified.length;
    const detail = failed
      ? `${passedCount} passed · ${failed} failed`
      : `${passedCount} passed`;
    return { ...state(QA_STATE.VERIFIED_RUN, detail), rows: facts };
  }
  if (hasState(entries, QA_STATE.STANDING_SOURCE)) {
    return {
      ...state(
        QA_STATE.STANDING_SOURCE,
        "This intake case was not run against the revision that is deployed.",
      ),
      rows: facts,
    };
  }
  if (hasState(entries, QA_STATE.FAILED)) {
    return { ...state(QA_STATE.FAILED), rows: facts };
  }
  return {
    ...state(
      QA_STATE.NEVER_ASKED,
      "Nobody asked a post-deploy question about this member.",
    ),
    rows: facts,
  };
}

const SATISFIED_RAW = new Set(["pass", "passed", "waived", "succeeded"]);

const DISCHARGED = new Set([
  QA_STATE.SUPERSEDED,
  QA_STATE.WAIVED,
  QA_STATE.NO_OBLIGATION,
  QA_STATE.RUN_MACHINERY,
]);

const PROVED = new Set([
  QA_STATE.VERIFIED_RUN,
  QA_STATE.VERIFIED_ITEM,
  QA_STATE.ADMITTED_COPY,
]);

function rawUnionLabel(row) {
  const outcome = outcomeOf(row);
  if (outcome === "pass") return "passed";
  if (outcome === "fail" || outcome === "error") return "failed";
  if (outcome === "undetermined") return "needs review";
  return outcome || "queued";
}

function unionEntry(row, rows) {
  const classified = classifyQaRow(row, rows);
  if (!classified) {
    const label = rawUnionLabel(row);
    return { label, outstanding: !SATISFIED_RAW.has(label) };
  }
  if (
    DISCHARGED.has(classified.id)
    || (
      classified.id === QA_STATE.STANDING_SOURCE
      && /Open is expected/.test(classified.detail)
    )
  ) {
    return { label: classified.label, outstanding: false };
  }
  if (classified.id === QA_STATE.ADMITTED_COPY) {
    return { label: classified.label, outstanding: !passed(row) };
  }
  if (PROVED.has(classified.id)) {
    return { label: classified.label, outstanding: false };
  }
  return { label: classified.label, outstanding: true };
}

function tally(entries, pick) {
  const counts = new Map();
  for (const entry of entries) {
    if (pick && !pick(entry)) continue;
    counts.set(entry.label, Number(counts.get(entry.label) || 0) + 1);
  }
  return [...counts.entries()].map(([label, n]) => `${n} ${label}`).join(" · ");
}

// The line an operator reads first on item Verification. A superseded case
// is discharged by its replacement; an open standing source beside its
// admitted copy is expected. Outstanding means the union still blocks.
export function summarizeQaUnion(rows) {
  const entries = (rows || []).map((row) => unionEntry(row, rows));
  const outstanding = entries.filter((entry) => entry.outstanding);
  return {
    counts: tally(entries),
    outstandingPhrase: tally(outstanding),
    satisfied: outstanding.length === 0,
  };
}

export function memberQaCaption(memberState) {
  const label = memberState?.label || LABELS[QA_STATE.NEVER_ASKED];
  const detail = memberState?.detail;
  if (!detail) return `QA · ${label}`;
  if (memberState.id === QA_STATE.VERIFIED_RUN) return `QA · ${label} · ${detail}`;
  return `QA · ${label}`;
}

export function qaStatePill(documentNode, classified) {
  if (!classified) return null;
  return statePill(documentNode, classified.pill, classified.label);
}

export function qaStateNote(documentNode, classified) {
  if (!classified?.detail) return null;
  if (classified.id === QA_STATE.VERIFIED_RUN) return null;
  return el(documentNode, "span", "qa-state-note", classified.detail);
}
