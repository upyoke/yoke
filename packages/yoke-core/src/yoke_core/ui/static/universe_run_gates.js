// The Gates region on a deployment run card.
//
// A pipeline that suspends on a person surfaces, without this, as a run that
// simply stops moving: a stage that never completes and nothing to act on.
// What the reader needs is the same decision the Inbox carries, seen from the
// delivery end -- which stage stopped, why, what backs it, and the control
// that ends it.
//
// The region draws only when the run has a gate. An empty Gates block on
// every card would assert a shape the flow does not have, and would teach the
// reader to skip the one place the answer eventually appears.

import { appendEvidence, approvalProse } from "./decision_gate_body.js";
import { el } from "./universe_view_support.js";

// A gate's label and its state are read from the kind, so the run card and
// the Inbox cannot disagree about what a request is called.
const GATE_LABELS = {
  deployment_stage_approval: { label: "Approval", state: "waiting" },
  qa_needs_review: { label: "QA", state: "needs review" },
};

function gateName(gate) {
  const facts = gate.subject_context || {};
  if (gate.kind === "deployment_stage_approval") return facts.stage || "stage";
  return facts.case_name || facts.plan_name || "check";
}

// Who the gate waits on, told from this reader's position. A gate they may
// answer names their own standing; one they may not names the address it was
// sent to, so a run halted on somebody else still says so.
function gateNote(gate) {
  if (gate.decided_by_you) {
    const action = gate.your_decision?.action;
    return action ? `you: ${action}d` : "you: answered";
  }
  if (gate.can_act) return `you: ${gate.authority_reason}`;
  const progress = gate.approval_progress || {};
  if (progress.waiting_on) return `waiting on ${progress.waiting_on}`;
  return "waiting on another approver";
}

function appendActions(documentNode, host, gate, onAct) {
  if (!gate.can_act || !onAct) return;
  const actions = el(documentNode, "div", "run-gate-actions");
  const available = Array.isArray(gate.actions) ? gate.actions : [];
  available.forEach((action, index) => {
    const button = el(
      documentNode,
      "button",
      `run-gate-action${index === available.length - 1 ? " is-primary" : ""}`,
      action,
    );
    button.type = "button";
    button.addEventListener("click", (event) => {
      // The card is a link to the run. A gate answered from inside it must
      // not also navigate away from the answer.
      event.preventDefault();
      event.stopPropagation();
      onAct(gate, action, host);
    });
    actions.appendChild(button);
  });
  host.appendChild(actions);
}

function appendGate(documentNode, host, gate, onAct) {
  const known = GATE_LABELS[gate.kind];
  if (!known) return;
  const wrap = el(
    documentNode,
    "div",
    `run-gate is-${known.state.replace(/ /g, "-")}`,
  );
  const line = el(documentNode, "div", "run-gate-line");
  line.appendChild(el(documentNode, "span", "run-gate-kind", known.label));
  line.appendChild(el(documentNode, "span", "run-gate-name", gateName(gate)));
  line.appendChild(el(documentNode, "span", "run-gate-state", known.state));
  line.appendChild(el(documentNode, "span", "run-gate-note", gateNote(gate)));
  wrap.appendChild(line);

  const why = approvalProse(gate);
  if (why) wrap.appendChild(el(documentNode, "p", "run-gate-why", why));
  if (gate.kind === "qa_needs_review") {
    appendEvidence(documentNode, wrap, gate.subject_context || {});
  }
  appendActions(documentNode, wrap, gate, onAct);
  host.appendChild(wrap);
}

export function appendRunGates(documentNode, card, gates, onAct) {
  const rows = (gates || []).filter((gate) => GATE_LABELS[gate.kind]);
  if (!rows.length) return null;
  const host = el(documentNode, "div", "run-gates");
  const head = el(documentNode, "div", "run-gates-head", "Gates ");
  head.appendChild(el(documentNode, "span", "run-gates-count", `· ${rows.length}`));
  host.appendChild(head);
  for (const gate of rows) appendGate(documentNode, host, gate, onAct);
  card.appendChild(host);
  return host;
}

// A run holds on a gate, so the status vocabulary needs a word for it: the
// generic status palette has none, and drawing the card's edge and its pill
// from separate sources left an amber-edged card wearing a grey pill.
export function runGateStatus(row) {
  const gates = (row.gates || []).filter((gate) => GATE_LABELS[gate.kind]);
  if (!gates.length) return null;
  return gates.some((gate) => gate.kind === "deployment_stage_approval")
    ? "awaiting approval"
    : "awaiting review";
}

export const universeRunGates = { appendRunGates, runGateStatus };
