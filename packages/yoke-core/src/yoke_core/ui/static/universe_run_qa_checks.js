// One run's QA checks as a reader judges them: each current check names the
// method that ran (linked to its QA case), its outcome, its verdict reason as
// plain text, and the screenshots that check captured. Attempts that were
// replaced stay together in one folded history. Shipping cards, the run page
// and the Inbox's run review all draw checks through here, so a screenshot is
// always shown under the check whose requirement owns it, and only once.

import { appendRunConclusion } from "./qa_run_conclusion.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { outcomeOf } from "./universe_run_verification.js";
import { el } from "./universe_view_support.js";

// Words a person's decision puts on a check the agent passed. A stage whose
// verdict needs a person is not passed until that person decides; the
// agent's passing check is evidence for the decision, not the decision.
const DECISION_OUTCOMES = {
  pending: "screenshots captured · awaiting approval",
  approved: "approved",
  rejected: "rejected",
  undetermined: "decided · outcome not recorded",
};

// One answered review's outcome. Only a recorded approve reads approved;
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

function passedLike(check) {
  return String(check?.outcome || "") === "passed";
}

export function checkOutcome(check, decision) {
  if (decision && passedLike(check)) return DECISION_OUTCOMES[decision];
  return outcomeOf(check);
}

// Where a person decides a run's checks, the answer on its run-level QA
// reviews, folded by `foldDecisions`. `null` when no person decides, which
// keeps agent-only verdicts reading "passed".
export function runHumanDecision(gates) {
  const reviews = (gates || []).filter((gate) => gate.kind === "qa_needs_review");
  return foldDecisions(reviews.map((gate) => (gate.status === "resolved"
    ? decidedOutcome(gate.resolution_action) : "pending")));
}

// The Run QA heading's verdict: the person's answer when one is owed,
// otherwise the checks' own tally.
export function runQaVerdict(checks, decision) {
  if (decision === "pending") {
    return { text: "Awaiting approval", tone: "is-awaiting" };
  }
  if (decision === "undetermined") {
    return { text: "Decided · outcome not recorded", tone: "is-undetermined" };
  }
  const passed = checks.filter(passedLike).length;
  const word = decision || "passed";
  return {
    text: `${passed} of ${checks.length} ${word}`,
    tone: passed === checks.length && decision !== "rejected"
      ? "is-approved" : "is-rejected",
  };
}

function ownArtifacts(check) {
  return (check.artifacts || []).map((artifact) => ({
    ...artifact, requirement_id: artifact.requirement_id ?? check.requirement_id,
  }));
}

export function runCheckLine(context, check, decision = null) {
  const documentNode = context.document;
  const line = el(documentNode, "div", "run-qa-check");
  const name = el(documentNode, "strong", "run-qa-check-name");
  name.appendChild(qaCaseLink(context, check, checkName(check)));
  line.appendChild(name);
  line.appendChild(el(
    documentNode, "span", "run-qa-check-outcome", checkOutcome(check, decision),
  ));
  // A passing check already states its result. Keep diagnostic context for
  // failures and unresolved checks, where the reason helps the reader act.
  if (check.verdict_reason && !passedLike(check)) {
    line.appendChild(el(
      documentNode, "p", "run-qa-check-reason", String(check.verdict_reason),
    ));
  }
  const strip = evidenceStrip(context, ownArtifacts(check), {
    compact: true, stepCaptionsOnly: true,
  });
  if (strip) line.appendChild(strip);
  // A CI check that captured nothing still names the Actions run it rests on.
  else appendRunConclusion(documentNode, line, check, "run-check-conclusion");
  return line;
}

// Current checks first, then replaced attempts folded with their own
// screenshots. Anything a caller appends after this (the decision) reads
// last, after every piece of evidence it rests on.
export function appendRunChecks(context, host, current, history, decision) {
  const documentNode = context.document;
  for (const check of current) host.appendChild(runCheckLine(context, check, decision));
  if (!history.length) return;
  const details = el(documentNode, "details", "run-qa-history");
  details.appendChild(el(documentNode, "summary", null,
    `${history.length} earlier or superseded check${history.length === 1 ? "" : "s"}`));
  for (const check of history) details.appendChild(runCheckLine(context, check));
  host.appendChild(details);
}

export const universeRunQaChecks = {
  appendRunChecks,
  checkName,
  checkOutcome,
  decidedOutcome,
  foldDecisions,
  qaCaseHref,
  qaCaseLink,
  runCheckLine,
  runHumanDecision,
  runQaVerdict,
};
