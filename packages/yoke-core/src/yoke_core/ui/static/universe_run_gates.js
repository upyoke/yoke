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

// The two kinds that reach a run. Anything else on the gates list is not a
// decision this card knows how to draw, and is left to the Inbox.
const RUN_GATE_KINDS = new Set(["deployment_stage_approval", "qa_needs_review"]);

export function runGates(row) {
  return (row?.gates || []).filter((gate) => RUN_GATE_KINDS.has(gate.kind));
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

export function appendRunGates(context, card, gates, onAct) {
  const documentNode = context.document;
  const rows = (gates || []).filter((gate) => RUN_GATE_KINDS.has(gate.kind));
  if (!rows.length) return null;
  const host = el(documentNode, "div", "run-requests");
  for (const gate of rows) {
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
  card.appendChild(host);
  return host;
}

// A run holds on a gate, so the status vocabulary needs a word for it: the
// generic status palette has none, and drawing the card's edge and its pill
// from separate sources left an amber-edged card wearing a grey pill.
export function runGateStatus(row) {
  const gates = runGates(row);
  if (!gates.length) return null;
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
