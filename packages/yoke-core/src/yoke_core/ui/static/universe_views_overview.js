// The Overview composes independent product reads without inventing facts.

import { el } from "./universe_view_support.js";
import { loadActivationModules } from "./universe_views_overview_activation.js";
import {
  sectionJumps,
  signalMasthead,
} from "./universe_views_overview_signals.js";
import {
  overviewSection,
  summaryPanel,
} from "./universe_overview_primitives.js";
import { loadVitals, loadStrategy } from "./universe_overview_strategy.js";
import { loadFrontier } from "./universe_overview_frontier.js";
import { loadSessions } from "./universe_overview_sessions.js";
import { loadDelivery } from "./universe_overview_delivery.js";

// The one entry point the shell calls. The activation stack pins above the
// scope picker (in the shell's above-scope host when one is supplied, else
// inline above the panels), so a project-selection change never tears it
// down; each panel below fills independently.
export function renderOverviewView(context, main, scope, options = {}) {
  const documentNode = context.document;
  const masthead = signalMasthead(documentNode);

  // Two questions, in the order an operator asks them: where is this universe
  // pointed, and what is happening right now. Everything the Overview shows
  // answers one of them, so everything it shows sits under one of two
  // headings — where six equal panels in a row said nothing about which
  // question each one served.
  const strategy = summaryPanel(documentNode, "Strategy", "strategy", scope, "Strategy");
  // Frontier is no longer a destination — this section IS what that
  // destination was — so its "open" link goes to Items, the view that answers
  // the follow-up question the section raises.
  // The third argument is the SECTION key — what the jump strip and the
  // detail line are keyed on. It used to double as the destination the panel
  // opens, because every section was named for its own view; two of them are
  // not any more, and the loaders own the link.
  const frontier = summaryPanel(
    documentNode, "Waiting and ready", "frontier", scope, "Frontier", "items",
  );
  const sessions = summaryPanel(documentNode, "Active", "sessions", scope, "Sessions");
  const delivery = summaryPanel(
    documentNode, "Shipping", "delivery", scope, "Delivery", "deployments",
  );
  const panels = new Map([
    ["strategy", strategy], ["frontier", frontier], ["sessions", sessions],
    ["delivery", delivery],
  ]);
  // Events and Doctor leave the Overview. Both are records you consult when
  // something already happened, which is the drawer's whole subject; neither
  // answers where this universe is pointed or what is happening now, and a
  // pulse you cannot act on is a screenshot of your own event table.
  const activationHost = el(documentNode, "div", "activation-host");
  const aboveScope = options.aboveScope || null;
  if (aboveScope) aboveScope.replaceChildren(activationHost);
  main.replaceChildren(
    sectionJumps(documentNode, panels), masthead,
    ...(aboveScope ? [] : [activationHost]),
    overviewSection(documentNode, "strategy", "Strategy", [strategy]),
    overviewSection(documentNode, "frontier", "Frontier", [
      frontier, sessions, delivery,
    ]),
  );

  // Each read is issued once at mount over the widest bucket set; a
  // project-selection change re-runs the held paint() closures (which read
  // getScope() live) with no refetch. Activation is scope-independent and
  // stays out of the rescope path entirely.
  let currentScope = scope;
  const getScope = () => currentScope;
  const painters = [];
  const hold = (pending) => Promise.resolve(pending).then((paint) => {
    if (typeof paint === "function") painters.push(paint);
  });

  const activationFacts = loadActivationModules(context, activationHost);
  const vitalsRead = loadVitals(context, masthead, getScope);
  vitalsRead.then((vitals) => {
    if (vitals && typeof vitals.paint === "function") painters.push(vitals.paint);
  });
  const timelinesRead = vitalsRead.then(
    (vitals) => (vitals && vitals.timelines) || [],
  );
  hold(loadStrategy(context, strategy, getScope, activationFacts, timelinesRead));
  hold(loadFrontier(context, frontier, getScope, activationFacts));
  hold(loadSessions(context, sessions, getScope));
  hold(loadDelivery(context, delivery, getScope, activationFacts));

  return {
    rescope(newScope) {
      if (!context.isMounted()) return;
      currentScope = newScope;
      for (const panel of panels.values()) panel.setScope(newScope);
      for (const paint of painters) paint();
    },
  };
}
