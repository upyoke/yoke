// What a view says where a deployment environment should be named and
// none is. Run cards, the item delivery panels, and the QA execution
// target view all render that same absence, so they read the wording
// from here rather than each carrying its own copy of the phrase.

// Shown in place of an environment name. It reports what the record
// holds — no environment is named — rather than diagnosing why, which
// the reader of a card cannot act on and which "unavailable" wrongly
// implies is a transient failure to reach one.
export const NO_ENVIRONMENT_LABEL = "no environment";

// Where an item stands in one environment, as a phrase that reads on its
// own: the Frontier's dependency cards, the compact delivery summary and the
// delivery box's pending row all say it from here so the wording cannot
// drift. The environment name is always data from the record; a record that
// names none gets the same sentence without the place, not a pretend name.
// "not deployed" is a merged item whose delivery there is still pending.
const DELIVERY_STATE_LABELS = {
  live: [(env) => `✓ Live in ${env}`, "✓ Live"],
  deploying: [(env) => `Deploying to ${env}`, "Deploying"],
  "not deployed": [(env) => `Merged · not in ${env} yet`, "Merged · not deployed yet"],
  failed: [(env) => `✗ Failed in ${env}`, "✗ Failed"],
};

export function deliveryStateLabel(state, environment) {
  const env = String(environment || "");
  const label = DELIVERY_STATE_LABELS[state];
  if (!label) return [env, state].filter(Boolean).join(" ");
  return env ? label[0](env) : label[1];
}
