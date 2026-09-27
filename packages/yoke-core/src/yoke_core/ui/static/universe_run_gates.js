// A deployment run's pending and resolved decisions, folded into its card.
//
// A pipeline that suspends on a person needs the same request the Inbox
// carries. Once answered, that request still names the evidence and person
// behind the decision, so the run card keeps it beside the recorded answer.

import { appendActions, reviewRequestCard } from "./review_request_card.js";
import { KIND_LABELS, reviewerLine } from "./review_request_presentation.js";
import { el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

// The two kinds that reach a run. Anything else on the gates list is not a
// decision this card knows how to draw, and is left to the Inbox.
const RUN_GATE_KINDS = new Set(["deployment_stage_approval", "qa_needs_review"]);

export function runGates(row) {
  return runDecisionGates(row).filter((gate) => gate.status !== "resolved");
}

export function runDecisionGates(row) {
  return (row?.gates || []).filter((gate) => RUN_GATE_KINDS.has(gate.kind));
}

// A gate row as the card expects a request: the run gate projection keys
// the request id and the request time differently from the Inbox row.
export function gateAsRequest(gate) {
  return {
    ...gate,
    id: gate.request_id,
    created_at: gate.created_at || gate.requested_at,
    // A resolved request is a record, even when the reader was not its
    // approver. The action and actor are shown beside its frozen evidence.
    ...(gate.status === "resolved" ? {
      actions: [], can_act: false, deciders: [], authority_reason: null,
      decided_by_you: false, your_decision: null,
    } : {}),
  };
}

export function resolvedDecisionRecord(documentNode, gate) {
  if (gate.status !== "resolved") return null;
  const action = gate.resolution_action === "approve" ? "Approved"
    : gate.resolution_action === "reject" ? "Rejected" : "Decided";
  const actor = gate.resolved_by || `actor ${gate.resolution_actor_id || "unknown"}`;
  const result = el(documentNode, "p", "run-decision-record");
  result.appendChild(el(documentNode, "span", null,
    `${action} by ${actor}${gate.resolved_at ? " · " : ""}`));
  if (gate.resolved_at) result.appendChild(relativeTime(documentNode, gate.resolved_at));
  return result;
}

// The person's side of a run QA review, after the evidence it rests on:
// a plain request with the answer buttons while it is open, the recorded
// answer once decided. The checks above already carry what was captured, so
// nothing here repeats the evidence, the run, or a restatement of the stage.
export function runQaDecision(context, gate, onAct) {
  const documentNode = context.document;
  const record = resolvedDecisionRecord(documentNode, gate);
  if (record) return record;
  const request = gateAsRequest(gate);
  const ask = el(documentNode, "div", "run-decision-ask");
  ask.appendChild(el(documentNode, "p", null, "Approve or reject the visual result."));
  const actions = Array.isArray(request.actions) ? request.actions : [];
  if (onAct && request.can_act !== false && actions.length) {
    appendActions(documentNode, ask, ask, request,
      (row, action, node, note) => onAct(gate, action, node, note));
  } else {
    const who = reviewerLine(request);
    if (who) ask.appendChild(el(documentNode, "span", "run-decision-who", who));
  }
  return ask;
}

export function runFinalizationNote(documentNode, row) {
  if (!(row.current_stage === "complete" && row.status === "executing")) return null;
  return el(documentNode, "p", "run-finalization-note",
    row.settling_at
      ? "Stages complete. Finalizing member delivery; the run remains open until every member closes. If settlement stopped, re-drive this run under the project deploy lock."
      : "Stages complete. Waiting for final checks and member delivery before this run can succeed.");
}

// A release approval freezes its subject's latest screenshots. Any a run
// check already drew stay under that check, so each shows once on the card.
function withoutDrawnScreenshots(request, drawnIds) {
  const evidence = request.subject_context?.evidence;
  if (!drawnIds?.size || !Array.isArray(evidence?.screenshots)) return request;
  const screenshots = evidence.screenshots.filter(
    (shot) => !drawnIds.has(String(shot.id ?? shot.artifact_id ?? "")));
  return {
    ...request,
    subject_context: { ...request.subject_context, evidence: { ...evidence, screenshots } },
  };
}

// ``options.drawnRequestIds`` names the requests a caller has already put on
// the page — a member's own review, drawn on that member's row. Skipping them
// here is what keeps one decision from appearing twice on one card with two
// sets of Approve controls. A run QA review is drawn as its decision alone; a
// release approval keeps its full request card. ``options.drawnArtifactIds``
// names the screenshots the run's checks already drew.
export function appendRunGates(context, card, row, onAct, options = {}) {
  const documentNode = context.document;
  const drawn = options.drawnRequestIds || new Set();
  const rows = runDecisionGates(row).filter(
    (gate) => !drawn.has(String(gate.request_id)));
  const note = runFinalizationNote(documentNode, row);
  if (!rows.length && !note) return null;
  const host = el(documentNode, "div", "run-requests");
  for (const gate of rows) {
    const wrap = el(documentNode, "div",
      `run-request${gate.status === "resolved" ? " is-resolved" : ""}`);
    if (gate.kind === "qa_needs_review") {
      wrap.appendChild(runQaDecision(context, gate, onAct));
      host.appendChild(wrap);
      continue;
    }
    wrap.appendChild(el(
      documentNode, "div", "run-request-kind", KIND_LABELS[gate.kind],
    ));
    wrap.appendChild(reviewRequestCard(context, withoutDrawnScreenshots(
      gateAsRequest(gate), options.drawnArtifactIds,
    ), {
      inline: true,
      onAct: onAct && gate.status !== "resolved"
        ? (request, action, node, text) => onAct(gate, action, node, text) : null,
    }));
    const decision = resolvedDecisionRecord(documentNode, gate);
    if (decision) wrap.appendChild(decision);
    host.appendChild(wrap);
  }
  if (note) host.appendChild(note);
  card.appendChild(host);
  return host;
}

// A run holds on a gate, so the status vocabulary needs a word for it: the
// generic status palette has none, and drawing the card's edge and its pill
// from separate sources left an amber-edged card wearing a grey pill.
export function runGateStatus(row) {
  const gates = runGates(row);
  if (!gates.length) {
    return row?.status === "executing" && row?.current_stage === "complete"
      ? "finalizing" : null;
  }
  return gates.some((gate) => gate.kind === "deployment_stage_approval")
    ? "awaiting approval"
    : "awaiting review";
}

export const universeRunGates = {
  appendRunGates,
  gateAsRequest,
  resolvedDecisionRecord,
  runDecisionGates,
  runFinalizationNote,
  runQaDecision,
  runGateStatus,
  runGates,
};
