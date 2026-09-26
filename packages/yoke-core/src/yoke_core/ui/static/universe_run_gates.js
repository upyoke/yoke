// The decision a deployment run is halted on, folded into its card.
//
// A pipeline that suspends on a person surfaces, without this, as a run that
// simply stops moving: a stage that never completes and nothing to act on.
// What the reader needs is the same decision the Inbox carries, seen from
// the delivery end, so the run card draws the same request card the Inbox
// does — inline, without a second frame — and answers through the same
// resolver.

import { reviewRequestCard } from "./review_request_card.js";
import { KIND_LABELS } from "./review_request_presentation.js";
import { el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

// The two kinds that reach a run. Anything else on the gates list is not a
// decision this card knows how to draw, and is left to the Inbox.
const RUN_GATE_KINDS = new Set(["deployment_stage_approval", "qa_needs_review"]);

export function runGates(row) {
  return (row?.gates || []).filter((gate) =>
    RUN_GATE_KINDS.has(gate.kind) && gate.status !== "resolved");
}

// A gate row as the card expects a request: the run gate projection keys
// the request id and the request time differently from the Inbox row.
export function gateAsRequest(gate) {
  return {
    ...gate,
    id: gate.request_id,
    created_at: gate.created_at || gate.requested_at,
  };
}

// ``options.drawnRequestIds`` names the requests a caller has already put on
// the page — a member's own review, drawn on that member's row. Skipping them
// here is what keeps one decision from appearing twice on one card with two
// sets of Approve controls.
export function appendRunGates(context, card, row, onAct, options = {}) {
  const documentNode = context.document;
  const gates = row.gates || [];
  const drawn = options.drawnRequestIds || new Set();
  const rows = (gates || []).filter(
    (gate) => RUN_GATE_KINDS.has(gate.kind)
      && !drawn.has(String(gate.request_id)),
  );
  if (!rows.length && !(row.current_stage === "complete" && row.status === "executing")) {
    return null;
  }
  const host = el(documentNode, "div", "run-requests");
  for (const gate of rows) {
    if (gate.status === "resolved") {
      const result = el(documentNode, "p", "run-decision-record");
      const action = gate.resolution_action === "approve" ? "Approved"
        : gate.resolution_action === "reject" ? "Rejected" : "Decided";
      const actor = gate.resolved_by || `actor ${gate.resolution_actor_id || "unknown"}`;
      result.appendChild(el(documentNode, "span", null, `${action} by ${actor} · `));
      if (gate.resolved_at) result.appendChild(relativeTime(documentNode, gate.resolved_at));
      host.appendChild(result);
      continue;
    }
    const wrap = el(documentNode, "div", "run-request");
    wrap.appendChild(el(
      documentNode, "div", "run-request-kind", KIND_LABELS[gate.kind],
    ));
    wrap.appendChild(reviewRequestCard(context, gateAsRequest(gate), {
      inline: true,
      onAct: onAct ? (row, action, node, note) => onAct(gate, action, node, note) : null,
    }));
    host.appendChild(wrap);
  }
  if (row.current_stage === "complete" && row.status === "executing") {
    host.appendChild(el(documentNode, "p", "run-finalization-note",
      row.settling_at
        ? "Stages complete. Finalizing member delivery; the run remains open until every member closes. If settlement stopped, re-drive this run under the project deploy lock."
        : "Stages complete. Waiting for final checks and member delivery before this run can succeed."));
  }
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
  runGateStatus,
  runGates,
};
