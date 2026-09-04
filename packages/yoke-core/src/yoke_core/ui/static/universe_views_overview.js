// The Overview answers two questions with live objects: Strategy shows where
// the universe is pointed; Frontier shows work moving through its five bands.

import { loadDelivery } from "./universe_overview_delivery.js";
import { loadFrontier } from "./universe_overview_frontier.js";
import {
  overviewBand,
  overviewSection,
} from "./universe_overview_primitives.js";
import { loadSessions } from "./universe_overview_sessions.js";
import { loadStrategy } from "./universe_overview_strategy.js";
import { el, settledScopedCalls } from "./universe_view_support.js";
import { loadActivationModules } from "./universe_views_overview_activation.js";

export function renderOverviewView(context, main, scope, options = {}) {
  const documentNode = context.document;
  if (typeof options.hidePageHead === "function") options.hidePageHead();

  const strategy = overviewSection(documentNode, "strategy", "Strategy");
  const standing = overviewBand(
    documentNode, "standing", "Standing", "No standing documents.",
  );
  const plans = overviewBand(
    documentNode, "plans", "Plans", "No plans in this scope.",
  );
  strategy.body.replaceChildren(standing, plans);

  const frontier = overviewSection(documentNode, "frontier", "Frontier");
  const waiting = overviewBand(
    documentNode, "waiting", "Waiting", "Nothing is stopped.",
  );
  const ready = overviewBand(
    documentNode, "ready", "Ready", "Nothing is ready to pick up.",
  );
  const active = overviewBand(
    documentNode,
    "active",
    "Active",
    "No session is running against this universe.",
  );
  const shipping = overviewBand(
    documentNode, "shipping", "Shipping", "No deployment run is in flight.",
  );
  const done = overviewBand(
    documentNode, "done", "Done (24h)", "Nothing finished in the last 24 hours.",
  );
  frontier.body.replaceChildren(waiting, ready, active, shipping, done);

  const activationHost = el(documentNode, "div", "activation-host");
  if (options.aboveScope) options.aboveScope.replaceChildren(activationHost);
  main.replaceChildren(
    ...(options.aboveScope ? [] : [activationHost]), strategy, frontier,
  );
  loadActivationModules(context, activationHost);

  let currentScope = scope;
  const getScope = () => currentScope;
  const painters = [];
  const hold = (pending) => Promise.resolve(pending).then((paint) => {
    if (typeof paint === "function") painters.push(paint);
  });
  // Active and Ready answer the same question from opposite sides, so they
  // read one session roster: Ready omits every item a session in Active
  // already holds.
  const sessionRoster = settledScopedCalls(context, [{
    functionId: "sessions.list",
    payload: { per_project: true },
  }]);
  hold(loadStrategy(context, { standing, plans }, getScope));
  hold(loadFrontier(context, { waiting, ready, done }, getScope, sessionRoster));
  hold(loadSessions(context, active, getScope, sessionRoster));
  hold(loadDelivery(context, shipping, getScope));

  return {
    rescope(nextScope) {
      if (!context.isMounted()) return;
      currentScope = nextScope;
      for (const paint of painters) paint();
    },
  };
}
