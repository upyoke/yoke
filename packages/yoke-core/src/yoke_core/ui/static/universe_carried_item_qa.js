// What a carried item's QA proved, drawn inside that item's entry on a run.
//
// The check that ran against the deployed revision leads, under "QA for the
// deployed revision", with its own screenshots. Every other check the item
// has — before merge, earlier releases, superseded or waived attempts — sits
// behind one "Earlier checks" disclosure, one row each, each linking its own
// QA case and, where the record carries one, its own run or CI run.

import {
  QA_KIND,
  QA_STATE,
  classifyQaRow,
  isPostDeployFact,
  ranAgainstDeployedRevision,
} from "./qa_state.js";
import { runConclusionUrl } from "./qa_run_conclusion.js";
import { drawnArtifacts, evidenceStrip } from "./review_evidence_strip.js";
import { deploymentRunHref } from "./universe_navigation.js";
import { qaCaseLink } from "./universe_run_qa_checks.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el } from "./universe_view_support.js";

// Screenshots shown before "and N more" opens the rest in place.
export const LATEST_VISUALS = 3;

const MARKS = { passed: "✓", failed: "✕", other: "○" };

function isRunMachinery(row) {
  return String(row?.qa_kind || "") === QA_KIND.STAGE_ACCEPTANCE;
}

export function isBeforeMergeCheck(row) {
  if (!row || isRunMachinery(row)) return false;
  return !isPostDeployFact(row) && !row.deployment_run_id;
}

function outcomeState(row) {
  const outcome = String(row?.outcome || "");
  if (outcome === "passed") return "passed";
  if (outcome === "failed") return "failed";
  return "other";
}

function outcomeWord(row) {
  return String(row?.outcome || "not run").replaceAll("_", " ");
}

function newestFirst(rows) {
  return [...rows].sort((left, right) => (
    (Date.parse(right.happened_at || "") || 0) - (Date.parse(left.happened_at || "") || 0)
  ));
}

function isScreenshot(artifact) {
  return String(artifact?.content_type || "").startsWith("image/")
    || String(artifact?.artifact_type || "").toLowerCase().includes("screenshot");
}

function hasOutput(row) {
  return (row.artifacts || []).some((artifact) => (
    String(artifact?.artifact_type || "").toLowerCase().includes("output")
  ));
}

function recordedOn(row, runId) {
  return Boolean(row.deployment_run_id)
    && String(row.deployment_run_id) === String(runId || "");
}

// The check that answers for the revision this run deployed: one whose
// observed lineage is the deployed revision, or one this very run recorded.
// A passing one is preferred over a newer failure it already answered.
export function deployedRevisionCheck(rows, { runId, deployedSha } = {}) {
  const candidates = newestFirst(rows).filter((row) => {
    if (isBeforeMergeCheck(row)) return false;
    const state = classifyQaRow(row, rows)?.id;
    if ([QA_STATE.SUPERSEDED, QA_STATE.WAIVED, QA_STATE.NO_OBLIGATION].includes(state)) {
      return false;
    }
    return ranAgainstDeployedRevision(row, deployedSha) || recordedOn(row, runId);
  });
  return candidates.find((row) => outcomeState(row) === "passed") || candidates[0] || null;
}

function methodPhrase(row) {
  const method = String(row.method_name || row.method_id || "Check");
  return /^command/i.test(method) ? "Command check" : method;
}

function runLink(documentNode, row, project) {
  const runId = String(row.deployment_run_id);
  const link = el(documentNode, "a", "carried-item-qa-run", `Run ${runId.replace(/^run-/, "")}`);
  link.href = deploymentRunHref(project, runId);
  return link;
}

function provenanceOf(row, rows, { runId, deployedSha }) {
  const state = classifyQaRow(row, rows)?.id;
  if (state === QA_STATE.SUPERSEDED) return "superseded";
  if (state === QA_STATE.WAIVED) return "waived";
  if (state === QA_STATE.NO_OBLIGATION) return "no obligation";
  if (ranAgainstDeployedRevision(row, deployedSha)) return "deployed revision";
  if (recordedOn(row, runId)) return "this release";
  return "older revision";
}

function qaRow(documentNode, row, parts) {
  const state = outcomeState(row);
  const line = el(documentNode, "p", `carried-item-qa-row is-${state}`);
  line.appendChild(el(documentNode, "span", "carried-item-qa-mark", MARKS[state]));
  parts.filter(Boolean).forEach((part, index) => {
    if (index) line.appendChild(el(documentNode, "span", "carried-item-qa-sep", "·"));
    line.appendChild(typeof part === "string" ? el(documentNode, "span", null, part) : part);
  });
  return line;
}

function age(row) {
  return row.happened_at ? relativeAgePhrase(row.happened_at) : null;
}

function currentRow(context, row, { runId, project }) {
  const documentNode = context.document;
  const line = qaRow(documentNode, row, [
    qaCaseLink(context, row, `${methodPhrase(row)} ${outcomeWord(row)}`),
    recordedOn(row, runId) ? "this release" : row.deployment_run_id
      ? runLink(documentNode, row, project) : null,
    age(row),
  ]);
  if (hasOutput(row)) {
    line.appendChild(el(documentNode, "span", "carried-item-qa-sep", "·"));
    line.appendChild(qaCaseLink(context, row, "View output", "carried-item-qa-output"));
  }
  return line;
}

function earlierRow(context, row, rows, options) {
  const documentNode = context.document;
  const parts = [];
  if (isBeforeMergeCheck(row)) {
    parts.push(qaCaseLink(context, row, "Before merge"), age(row));
    const url = runConclusionUrl(row);
    if (url) {
      const link = el(documentNode, "a", "carried-item-qa-ci", "GitHub Actions");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      parts.push(link);
    } else {
      parts.push(String(row.method_name || row.method_id || "") || null);
    }
  } else {
    parts.push(row.deployment_run_id
      ? runLink(documentNode, row, options.project) : "After deploy");
    parts.push(age(row));
    parts.push(qaCaseLink(context, row, provenanceOf(row, rows, options)));
  }
  if (outcomeState(row) !== "passed") parts.push(outcomeWord(row));
  return qaRow(documentNode, row, parts);
}

// Every screenshot the item's checks captured, each once under the check
// that owns it: the lead check's first, then the rest newest first. The
// strip shows three and opens the others in place.
function screenshots(context, lead, rows) {
  const seen = new Set();
  const shots = [];
  for (const row of [lead, ...newestFirst(rows.filter((other) => other !== lead))]) {
    for (const artifact of row?.artifacts || []) {
      const key = String(artifact.id ?? artifact.artifact_id ?? "");
      if (!isScreenshot(artifact) || (key && seen.has(key))) continue;
      if (key) seen.add(key);
      shots.push({ ...artifact,
        requirement_id: artifact.requirement_id ?? row.requirement_id });
    }
  }
  const options = { compact: true, limit: LATEST_VISUALS, stepCaptionsOnly: true };
  const strip = evidenceStrip(context, shots, options);
  return { strip, drawn: strip ? drawnArtifacts(shots, options) : [] };
}

// `options`: runId, deployedSha, project (for run links). Returns the
// screenshots drawn, so a review whose evidence is already on screen can
// leave it out.
export function paintCarriedItemQa(context, wrap, rows, options = {}) {
  const documentNode = context.document;
  const checks = (rows || []).filter((row) => !isRunMachinery(row));
  const current = deployedRevisionCheck(checks, options);
  const shown = [];
  if (current) {
    wrap.appendChild(el(documentNode, "p", "carried-item-qa-heading",
      "QA for the deployed revision"));
    wrap.appendChild(currentRow(context, current, options));
    const { strip, drawn } = screenshots(context, current, checks);
    if (strip) wrap.appendChild(strip);
    shown.push(...drawn);
  }
  const earlier = newestFirst(checks.filter((row) => row !== current));
  if (earlier.length) {
    const details = el(documentNode, "details", "carried-item-qa-earlier");
    details.appendChild(el(documentNode, "summary", null, "Earlier checks"));
    // With nothing run against the deployed revision, the item's pictures
    // stay reachable here rather than leading the entry.
    const strip = current ? null : screenshots(context, earlier[0], checks).strip;
    if (strip) details.appendChild(strip);
    for (const row of earlier) details.appendChild(earlierRow(context, row, checks, options));
    wrap.appendChild(details);
  }
  return { shown };
}

export const universeCarriedItemQa = {
  LATEST_VISUALS,
  deployedRevisionCheck,
  isBeforeMergeCheck,
  paintCarriedItemQa,
};
