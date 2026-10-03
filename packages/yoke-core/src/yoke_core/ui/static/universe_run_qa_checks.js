// QA checks as a reader judges them, for a run's own checks and a carried
// item's alike: each current check names the method that ran (linked to its
// QA case), a status mark and its result, its verdict reason as plain text,
// and the screenshots that check captured. Attempts that were replaced stay
// together in one folded "Earlier checks" history, each naming the run or
// merge it came from. Shipping cards, the run page and the Inbox's run
// review all draw checks through here, so a screenshot is always shown under
// the check whose requirement owns it, and only once.
//
// A check's result is the check's own verdict. A person's decision is a
// separate record drawn after the evidence, never a word on the check.

import { QA_KIND, QA_STATE, classifyQaRow, isPostDeployFact } from "./qa_state.js";
import { appendRunConclusion } from "./qa_run_conclusion.js";
import { drawnArtifacts, evidenceStrip } from "./review_evidence_strip.js";
import { buildUniverseRoute, deploymentRunHref } from "./universe_navigation.js";
import { outcomeOf } from "./universe_run_verification.js";
import { el } from "./universe_view_support.js";

const MARKS = { passed: "✓", failed: "✕", other: "○" };
const CHECK_STRIP = Object.freeze({ compact: true, stepCaptionsOnly: true });

// One answered decision's outcome. Only a recorded approve reads approved;
// a missing, empty or unknown action is a decision whose outcome the record
// does not name, never an approval.
export function decidedOutcome(action) {
  if (action === "approve") return "approved";
  if (action === "reject" || action === "deny" || action === "request_changes") {
    return "rejected";
  }
  return "undetermined";
}

// Several answers fold with rejection first, then anything still open, then
// any unnamed outcome; only all-approved reads approved.
export function foldDecisions(outcomes) {
  if (!outcomes.length) return null;
  for (const state of ["rejected", "pending", "undetermined"]) {
    if (outcomes.includes(state)) return state;
  }
  return "approved";
}

function projectIdOf(context, project) {
  if (project == null || project === "") return null;
  const projects = typeof context.projects === "function" ? context.projects() : [];
  const match = projects.find((candidate) => [candidate.id, candidate.slug].some(
    (value) => String(value) === String(project),
  ));
  return String(match ? match.id : project);
}

// The QA case page for the requirement a check or history row ran.
export function qaCaseHref(context, row) {
  if (row?.requirement_id == null) return null;
  return buildUniverseRoute(
    "qa-activity", projectIdOf(context, row.project ?? row.project_id),
    String(row.requirement_id),
  );
}

export function qaCaseLink(context, row, text, className = null) {
  const href = qaCaseHref(context, row);
  if (!href) return el(context.document, "span", className, text);
  const link = el(context.document, "a", className, text);
  link.href = href;
  return link;
}

// What ran, never the case key: `current-release-review-state` is an
// internal handle, and the method is what a reader recognises.
export function checkName(check) {
  return String(check?.method_name || check?.method_id || "Check");
}

function outcomeState(check) {
  if (check?.retracted_at) return "other";
  const outcome = String(check?.outcome || "");
  if (outcome === "passed") return "passed";
  if (outcome === "failed") return "failed";
  return "other";
}

// The check's own result: "Passed", "Failed", or the state it stands in.
export function checkOutcome(check) {
  if (check?.retracted_at) return "Cancelled";
  const state = outcomeState(check);
  if (state === "passed") return "Passed";
  if (state === "failed") return "Failed";
  const label = String(outcomeOf(check) || "");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

// A check recorded before the item merged: no run, and not a post-deploy fact.
export function isBeforeMergeCheck(row) {
  if (!row || String(row.qa_kind || "") === QA_KIND.STAGE_ACCEPTANCE) return false;
  return !isPostDeployFact(row) && !row.deployment_run_id;
}

// A person's answers on the decisions a section draws, folded by
// `foldDecisions`. `null` when no person decides, which keeps agent-only
// verdicts reading their own tally.
export function runHumanDecision(gates) {
  return foldDecisions((gates || []).map((gate) => (gate.status === "resolved"
    ? decidedOutcome(gate.resolution_action) : "pending")));
}

// A section heading's verdict: a person's open or refused decision when one
// is owed, otherwise the checks' own tally.
export function runQaVerdict(checks, decision) {
  if (decision === "pending") {
    return { text: "Awaiting approval", tone: "is-awaiting" };
  }
  if (decision === "rejected") return { text: "Rejected", tone: "is-rejected" };
  if (decision === "undetermined") {
    return { text: "Decided · outcome not recorded", tone: "is-undetermined" };
  }
  checks = checks.filter((check) => ![QA_STATE.CANCELLED, QA_STATE.NO_OBLIGATION,
    QA_STATE.WAIVED, QA_STATE.SUPERSEDED].includes(classifyQaRow(check)?.id));
  if (!checks.length) return { text: "", tone: "" };
  const passed = checks.filter((check) => outcomeState(check) === "passed").length;
  return {
    text: `${passed} of ${checks.length} passed`,
    tone: passed === checks.length ? "is-approved" : "is-rejected",
  };
}

function ownArtifacts(check) {
  return (check.artifacts || []).map((artifact) => ({
    ...artifact, requirement_id: artifact.requirement_id ?? check.requirement_id,
  }));
}

// Where an earlier attempt came from, when it is not the run on screen: its
// own run, linked, or the merge it verified.
function provenance(documentNode, check, { runId, project }) {
  const recorded = String(check.deployment_run_id || "");
  if (recorded && recorded !== String(runId || "")) {
    const link = el(documentNode, "a", "run-qa-check-run",
      `Run ${recorded.replace(/^run-/, "")}`);
    link.href = deploymentRunHref(project ?? check.project_id ?? null, recorded);
    return link;
  }
  return isBeforeMergeCheck(check)
    ? el(documentNode, "span", "run-qa-check-run", "Before merge") : null;
}

function separator(documentNode) {
  return el(documentNode, "span", "run-qa-check-sep", "·");
}

// `options`: runId (the run on screen) and project, which place an earlier
// attempt recorded elsewhere.
export function runCheckLine(context, check, options = {}) {
  const documentNode = context.document;
  const state = outcomeState(check);
  const line = el(documentNode, "div", `run-qa-check is-${state}`);
  line.appendChild(el(documentNode, "span", "run-qa-check-mark", MARKS[state]));
  const name = el(documentNode, "strong", "run-qa-check-name");
  name.appendChild(qaCaseLink(context, check, checkName(check)));
  line.appendChild(name);
  line.appendChild(separator(documentNode));
  line.appendChild(el(documentNode, "span", "run-qa-check-outcome", checkOutcome(check)));
  const origin = provenance(documentNode, check, options);
  if (origin) {
    line.appendChild(separator(documentNode));
    line.appendChild(origin);
  }
  // A passing check already states its result. Keep diagnostic context for
  // failures and unresolved checks, where the reason helps the reader act.
  const reason = check.retracted_at
    ? classifyQaRow(check)?.detail : check.verdict_reason;
  if (reason && state !== "passed") {
    line.appendChild(el(
      documentNode, "p", "run-qa-check-reason", String(reason),
    ));
  }
  const strip = evidenceStrip(context, ownArtifacts(check), CHECK_STRIP);
  if (strip) line.appendChild(strip);
  // A CI check that captured nothing still names the Actions run it rests on.
  else appendRunConclusion(documentNode, line, check, "run-check-conclusion");
  return line;
}

// Current checks first, then replaced attempts folded with their own
// screenshots. Anything a caller appends after this (the decision) reads
// last, after every piece of evidence it rests on.
export function appendRunChecks(context, host, current, history, options = {}) {
  const documentNode = context.document;
  for (const check of current) host.appendChild(runCheckLine(context, check, options));
  if (!history.length) return;
  const details = el(documentNode, "details", "run-qa-history");
  details.appendChild(el(documentNode, "summary", null,
    `Earlier checks (${history.length})`));
  for (const check of history) details.appendChild(runCheckLine(context, check, options));
  host.appendChild(details);
}

// The artifact ids the given check lines put on the page — each cut at its
// strip's own limit, since what "+N more" folds away is not drawn until
// opened — so a decision leaves out exactly what its section already holds.
export function drawnCheckArtifactIds(checks) {
  return new Set((checks || []).flatMap((check) => drawnArtifacts(
    ownArtifacts(check), CHECK_STRIP,
  ).map((artifact) => String(artifact.id))));
}

// One QA scope — "Run QA" or "Item QA" — with its heading, verdict, current
// checks and folded history. The caller appends the scope's decisions.
export function qaScopeSection(context, { heading, headingTag, current, history,
  decision, runId, project, className }) {
  const documentNode = context.document;
  const section = el(documentNode, "section",
    `run-qa-section${className ? ` ${className}` : ""}`);
  const head = el(documentNode, "div", "run-qa-head");
  head.appendChild(el(documentNode, headingTag || "h3", null, heading));
  // A scope with no checks has no tally; only a decision still owed or
  // refused heads it, and an approval is its own record below.
  if (current.length || (decision && decision !== "approved")) {
    const verdict = runQaVerdict(current, decision);
    if (verdict.text) head.appendChild(el(
      documentNode, "span", `run-verdict ${verdict.tone}`, verdict.text));
  }
  section.appendChild(head);
  appendRunChecks(context, section, current, history, { runId, project });
  return section;
}

export const universeRunQaChecks = {
  appendRunChecks,
  checkName,
  checkOutcome,
  decidedOutcome,
  drawnCheckArtifactIds,
  foldDecisions,
  isBeforeMergeCheck,
  qaCaseHref,
  qaCaseLink,
  qaScopeSection,
  runCheckLine,
  runHumanDecision,
  runQaVerdict,
};
