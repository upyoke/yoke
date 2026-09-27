// The two things a run page says about how far it got and what it proved:
// the stage rail it is moving along, and the checks it recorded.

import { classifyQaRow } from "./qa_state.js";
import { el } from "./universe_view_support.js";

const STEP_MARKS = {
  complete: "\u2713", active: "\u25d4", failed: "\u2715", stopped: "\u25a0",
};

export function appendSteps(documentNode, host, stages) {
  const steps = el(documentNode, "div", "run-steps");
  (stages || []).forEach((stage, index) => {
    const state = String(stage.state || "pending");
    const step = el(documentNode, "div", `run-step is-${state}`);
    step.appendChild(el(documentNode, "i", null, STEP_MARKS[state] || String(index + 1)));
    step.appendChild(el(documentNode, "span", null, String(stage.name)));
    // A stage that failed says so on its own row; the mark alone left a
    // reader to tell four states apart by glyph.
    if (state !== "pending" && state !== "complete") {
      step.appendChild(el(documentNode, "span", "run-step-state", state));
    }
    if (stage.failure) {
      step.appendChild(el(
        documentNode, "span", "run-step-failure", String(stage.failure),
      ));
    }
    steps.appendChild(step);
  });
  host.appendChild(steps);
}

function rawOutcome(check) {
  return String(check.outcome || "queued").replaceAll("_", " ");
}

export function outcomeOf(check) {
  return classifyQaRow(check)?.label || rawOutcome(check);
}
