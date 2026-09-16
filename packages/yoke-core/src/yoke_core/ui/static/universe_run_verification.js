// The two things a run page says about how far it got and what it proved:
// the stage rail it is moving along, and the checks it recorded.

import { evidenceStrip } from "./review_evidence_strip.js";
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

export function outcomeOf(check) {
  return String(check.outcome || "queued").replaceAll("_", " ");
}

// What the run's checks found, and the pictures each of them took.
//
// Every artifact here arrived attached to the check that recorded it, so it
// is drawn under that check rather than pooled into one strip at the foot of
// the card. A pool made a reader guess which check a screenshot came from,
// and a guess about evidence is the one thing evidence must not require.
export function verificationCard(context, checks) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "run-card");
  const heading = el(documentNode, "h2", null, "Verification");
  if (checks.length) {
    const passed = checks.filter((check) => check.outcome === "passed").length;
    heading.appendChild(el(
      documentNode,
      `span`,
      `run-verdict ${passed === checks.length ? "is-approved" : "is-rejected"}`,
      `${passed} of ${checks.length} passed`,
    ));
  }
  card.appendChild(heading);
  if (!checks.length) {
    card.appendChild(el(
      documentNode, "p", "run-copy", "No checks were recorded on this run.",
    ));
  }
  for (const check of checks) {
    const line = el(documentNode, "div", `run-check is-${outcomeOf(check).replace(/ /g, "-")}`);
    line.appendChild(el(documentNode, "i", null, check.outcome === "passed" ? "✓" : "✕"));
    line.appendChild(el(
      documentNode, "b", null, [check.case_key, check.method_name].filter(Boolean).join(" · "),
    ));
    line.appendChild(el(documentNode, "span", null, outcomeOf(check)));
    // An agent's reason can run to a paragraph; it folds under the check so
    // the list stays a list and the reason stays one click away.
    if (check.verdict_reason) {
      const reason = el(documentNode, "details", "run-check-reason");
      reason.appendChild(el(documentNode, "summary", null, "What the agent said"));
      reason.appendChild(el(documentNode, "p", null, String(check.verdict_reason)));
      line.appendChild(reason);
    }
    const strip = evidenceStrip(
      context,
      (check.artifacts || []).map(
        (artifact) => ({ ...artifact, requirement_id: check.requirement_id }),
      ),
      { compact: true },
    );
    if (strip) {
      strip.classList.add("run-check-evidence");
      line.appendChild(strip);
    }
    card.appendChild(line);
  }
  return card;
}

