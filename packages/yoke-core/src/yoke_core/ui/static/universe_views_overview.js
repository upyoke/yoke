// The Overview composes independent product reads without inventing facts.

import { el } from "./universe_view_support.js";
import { loadActivationModules } from "./universe_views_overview_activation.js";
import {
  sectionJumps,
  signalMasthead,
} from "./universe_views_overview_signals.js";
import { summaryPanel } from "./universe_overview_primitives.js";
import { loadVitals, loadStrategy } from "./universe_overview_strategy.js";
import { loadFrontier } from "./universe_overview_frontier.js";
import { loadSessions } from "./universe_overview_sessions.js";
import { loadDelivery } from "./universe_overview_delivery.js";
import { loadDoctor, loadEvents } from "./universe_overview_health.js";

// The one entry point the shell calls. The activation stack pins above the
// scope picker (in the shell's above-scope host when one is supplied, else
// inline above the panels), so a project-selection change never tears it
// down; each panel below fills independently.
export function renderOverviewView(context, main, scope, options = {}) {
  const documentNode = context.document;
  const masthead = signalMasthead(documentNode);

  const strategy = summaryPanel(documentNode, "Strategy", "strategy", scope, "Strategy");
  const frontier = summaryPanel(documentNode, "Frontier", "frontier", scope, "Frontier");
  const sessions = summaryPanel(documentNode, "Sessions", "sessions", scope, "Sessions");
  const delivery = summaryPanel(documentNode, "Delivery", "delivery", scope, "Delivery");
  const events = summaryPanel(documentNode, "Events", "events", scope, "Events");
  const doctor = summaryPanel(documentNode, "Doctor", "doctor", scope, "Doctor");
  const panels = new Map([
    ["strategy", strategy], ["frontier", frontier], ["sessions", sessions],
    ["delivery", delivery], ["events", events], ["doctor", doctor],
  ]);
  const finalPair = el(documentNode, "div", "overview-pair");
  finalPair.appendChild(events);
  finalPair.appendChild(doctor);
  const activationHost = el(documentNode, "div", "activation-host");
  const aboveScope = options.aboveScope || null;
  if (aboveScope) aboveScope.replaceChildren(activationHost);
  main.replaceChildren(
    sectionJumps(documentNode, panels), masthead,
    ...(aboveScope ? [] : [activationHost]),
    strategy, frontier, sessions, delivery, finalPair,
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
  hold(loadEvents(context, events, getScope));
  hold(loadDoctor(context, doctor, getScope));

  return {
    rescope(newScope) {
      if (!context.isMounted()) return;
      currentScope = newScope;
      for (const panel of panels.values()) panel.setScope(newScope);
      for (const paint of painters) paint();
    },
  };
}
