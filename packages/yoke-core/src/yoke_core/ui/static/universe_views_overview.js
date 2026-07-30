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

  const vitalsRead = loadVitals(context, masthead, scope);
  const activationFacts = loadActivationModules(context, activationHost);
  loadStrategy(context, strategy, scope, activationFacts, vitalsRead);
  loadFrontier(context, frontier, scope, activationFacts);
  loadSessions(context, sessions, scope);
  loadDelivery(context, delivery, scope, activationFacts);
  loadEvents(context, events, scope);
  loadDoctor(context, doctor, scope);
}
