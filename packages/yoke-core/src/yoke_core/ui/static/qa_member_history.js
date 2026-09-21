// What a carried item has actually been checked for — every phase, every
// run — summarised on the folded face and listed when expanded.
//
// A release card used to keep one answer per member for the run being
// viewed. That hid older screenshots behind a later command check, and it
// painted a pre-merge CI pass in the post-deploy slot whenever this run
// had asked nothing. History is a different question from "what proved
// this release", so the two stay labelled as themselves.

import {
  QA_KIND,
  QA_STATE,
  classifyMemberQa,
  classifyQaRow,
  isPostDeployFact,
  memberQaCaption,
  qaStateNote,
  ranAgainstDeployedRevision,
} from "./qa_state.js";
import {
  drawnArtifacts,
  evidenceStrip,
} from "./review_evidence_strip.js";
import { appendMoreDisclosure } from "./universe_sessions_holdings_disclosure.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el } from "./universe_view_support.js";

export const LATEST_VISUALS = 3;

function isRunMachinery(row) {
  return String(row?.qa_kind || "") === QA_KIND.STAGE_ACCEPTANCE;
}

export function isBeforeMergeCheck(row) {
  if (!row || isRunMachinery(row)) return false;
  if (isPostDeployFact(row)) return false;
  return !row.deployment_run_id;
}

export function historyChecks(rows) {
  return (rows || []).filter((row) => !isRunMachinery(row));
}

function isScreenshot(artifact) {
  return String(artifact?.content_type || "").startsWith("image/")
    || String(artifact?.artifact_type || "").toLowerCase().includes("screenshot");
}

// Screenshots in recency order across every check, not just the latest
// check. An item whose visual review passed and then had a command case
// still has pictures; they live on the earlier row.
export function latestVisualArtifacts(rows, { runId, deployedSha } = {}) {
  const seen = new Set();
  const ranked = [];
  for (const row of historyChecks(rows)) {
    const when = Date.parse(row.happened_at || "") || 0;
    for (const artifact of row.artifacts || []) {
      if (!isScreenshot(artifact)) continue;
      const key = String(artifact.id ?? artifact.artifact_id ?? "");
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      ranked.push({
        when,
        artifact: {
          ...artifact,
          requirement_id: row.requirement_id,
          provenance: checkProvenance(row, { runId, deployedSha }, rows),
        },
      });
    }
  }
  ranked.sort((left, right) => right.when - left.when);
  return ranked.map((entry) => entry.artifact);
}

export function checkProvenance(row, { runId, deployedSha } = {}, rows = []) {
  const classified = classifyQaRow(row, rows);
  if (isBeforeMergeCheck(row) || classified?.id === QA_STATE.VERIFIED_ITEM) {
    return "verified before merge";
  }
  if (
    classified?.id === QA_STATE.WAIVED
    || classified?.id === QA_STATE.NO_OBLIGATION
    || classified?.id === QA_STATE.SUPERSEDED
    || classified?.id === QA_STATE.RUN_MACHINERY
  ) {
    return classified.label;
  }
  if (ranAgainstDeployedRevision(row, deployedSha)) {
    return "ran against the deployed revision";
  }
  return "not the revision that is deployed";
}

export function historyCaption(rows, { runId, deployedSha } = {}) {
  const memberState = classifyMemberQa(rows, { runId });
  const options = { runId, deployedSha };
  let matched = 0;
  let beforeMerge = 0;
  let otherRevision = 0;
  for (const row of historyChecks(rows)) {
    const provenance = checkProvenance(row, options, rows);
    if (provenance === "verified before merge") beforeMerge += 1;
    else if (provenance === "ran against the deployed revision") matched += 1;
    else if (provenance === "not the revision that is deployed") otherRevision += 1;
  }
  const parts = [];
  if (matched) parts.push("QA · ran against the deployed revision");
  else if (otherRevision) parts.push("QA · not the revision that is deployed");
  else parts.push(memberQaCaption(memberState));
  if (beforeMerge) {
    parts.push(`${beforeMerge} verified before merge`);
  }
  return parts.join(" · ");
}

function phaseLabel(row, runId) {
  const phase = String(row?.qa_phase || "");
  if (isBeforeMergeCheck(row) || phase === "verification") return "before merge";
  const recorded = String(row?.deployment_run_id || "");
  if (phase === "post_deploy" && recorded && recorded === String(runId || "")) {
    return "this release";
  }
  if (phase === "post_deploy") return "post-deploy";
  return phase || "check";
}

function historyEntry(documentNode, row, options = {}, rows = []) {
  const item = el(documentNode, "li", "carried-item-history-entry");
  const provenance = checkProvenance(row, options, rows);
  const provenanceNode = el(
    documentNode, "span", "carried-item-history-provenance", provenance,
  );
  provenanceNode.setAttribute("data-provenance", provenance);
  item.appendChild(provenanceNode);
  const meta = [
    phaseLabel(row, options.runId),
    row.deployment_run_id || null,
    row.happened_at ? relativeAgePhrase(row.happened_at) : null,
    row.method_name || row.method_id || null,
    row.outcome || null,
    row.proof_summary || null,
  ].filter(Boolean);
  item.appendChild(el(
    documentNode, "span", "carried-item-history-meta", meta.join(" · "),
  ));
  return item;
}

function groupKey(itemId, runId) {
  return `${itemId}|${runId || ""}`;
}

// Caption, this-run honesty note, latest pictures, and the expandable
// history. Reviews stay with the caller: they are live work, not history.
export function paintMemberHistory(context, wrap, options = {}) {
  const { itemId, runId, facts, history, memberState, deployedSha } = options;
  const provenance = { runId, deployedSha };
  const documentNode = context.document;
  const rows = historyChecks(history);
  wrap.appendChild(el(
    documentNode,
    "span",
    "carried-item-evidence-caption",
    historyCaption(history, provenance),
  ));
  const note = qaStateNote(documentNode, memberState);
  if (note) wrap.appendChild(note);
  const cutShort = [groupKey(itemId, runId), groupKey(itemId, null)].some(
    (key) => facts?.truncatedGroups?.has(key),
  );
  if (cutShort) {
    wrap.appendChild(el(
      documentNode,
      "span",
      "carried-item-evidence-note",
      `Showing at most ${facts.perGroupLimit || 20} checks per `
        + "release; older ones are on the item.",
    ));
  }
  const visuals = latestVisualArtifacts(history, provenance);
  const stripOptions = {
    compact: true, limit: LATEST_VISUALS, stepCaptionsOnly: true,
  };
  const strip = evidenceStrip(context, visuals, stripOptions);
  if (strip) wrap.appendChild(strip);
  if (rows.length) {
    const region = el(documentNode, "ol", "carried-item-history");
    region.setAttribute("aria-label", "QA history");
    for (const row of rows) {
      region.appendChild(historyEntry(documentNode, row, provenance, history));
    }
    wrap.appendChild(region);
    appendMoreDisclosure(documentNode, wrap, {
      key: `member-qa:${itemId}:${runId || ""}`,
      hiddenCount: rows.length,
      region,
      label: "checks",
      className: "carried-item-history-more",
    });
  }
  return {
    drewEvidence: Boolean(strip),
    shown: strip ? drawnArtifacts(visuals, stripOptions) : [],
  };
}
