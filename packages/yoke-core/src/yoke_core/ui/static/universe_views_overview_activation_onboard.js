// The /yoke onboard module's body, drawn from the engine's live checklist
// facts. The module used to print one fixed execution-ready sentence for
// its activated state, which a run blocked at its first hosting step still
// showed — over a universe with no scaffold and no environments. Every
// sentence here now comes from the run: what it is stuck on, what it is
// waiting for, how far it got, and which outcomes it actually produced.

import { el } from "./universe_view_support.js";
import {
  ONBOARD_NO_RUN,
  ONBOARD_OUTCOMES,
  onboardBlockedLine,
  onboardCompleteLine,
  onboardEnvironmentsOutcome,
  onboardNextLine,
  onboardStepsLine,
  onboardSupersededLine,
} from "./universe_views_overview_activation_copy.js";

const COMPLETE = "complete";
const SUPERSEDED = "superseded";

function completedOutcomes(onboard) {
  const outcomes = [];
  if (onboard.strategy_docs) outcomes.push(ONBOARD_OUTCOMES.strategy);
  if (onboard.scaffold_installed) outcomes.push(ONBOARD_OUTCOMES.scaffold);
  const environments = onboard.environments || [];
  if (environments.length) {
    outcomes.push(onboardEnvironmentsOutcome(environments));
  }
  return outcomes;
}

// A blocker outranks the next step: an open run whose current row refused
// needs its reason on the card, not the row's title alone.
function leadLine(onboard) {
  if (onboard.blocker) {
    return onboardBlockedLine(
      onboard.blocker.step, onboard.blocker.title, onboard.blocker.detail,
    );
  }
  return onboard.next
    ? onboardNextLine(onboard.next.step, onboard.next.title)
    : ONBOARD_NO_RUN;
}

// The run drives the copy, not the module's latched state: a card that
// activated on an earlier complete run still reports a later run honestly.
export function onboardBody(documentNode, module, body) {
  const onboard = module.onboard;
  if (!onboard) {
    if (module.state === "in_progress") {
      body.appendChild(el(
        documentNode, "p", "activation-copy", ONBOARD_NO_RUN,
      ));
    }
    return;
  }
  if (onboard.run_status === COMPLETE) {
    body.appendChild(el(
      documentNode, "p", "activation-copy",
      onboardCompleteLine(completedOutcomes(onboard)),
    ));
    return;
  }
  if (onboard.run_status === SUPERSEDED) {
    const by = onboard.superseded_by || {};
    body.appendChild(el(
      documentNode, "p", "activation-copy",
      onboardSupersededLine(by.deployment_run_id, by.at),
    ));
    return;
  }
  body.appendChild(el(
    documentNode, "p", "activation-copy", leadLine(onboard),
  ));
  body.appendChild(el(
    documentNode, "p", "activation-progress",
    onboardStepsLine(onboard.steps_done, onboard.steps_total),
  ));
}
