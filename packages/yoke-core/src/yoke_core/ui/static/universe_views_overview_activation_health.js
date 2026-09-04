// Overview harness cards: one card per supported surface, each carrying the
// name, the version the relay reported, and one sentence saying what we
// detected there. Colour is a secondary cue on the status line; the words
// carry the meaning, so a viewer never has to decode a palette.

import { el } from "./universe_view_support.js";
import {
  harnessStatusLine,
  hookTrustRemediation,
} from "./universe_views_overview_activation_copy.js";

const HEALTH_RED = "red";

function unapprovedTrustSurfaces(targets) {
  const surfaces = [];
  for (const target of targets || []) {
    if (target.hook_health !== HEALTH_RED || !target.trust_surface) continue;
    if (!surfaces.includes(target.trust_surface)) {
      surfaces.push(target.trust_surface);
    }
  }
  return surfaces;
}

function lastSeenDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", timeZone: "UTC",
  }).format(date);
}

function harnessCard(documentNode, target) {
  const card = el(documentNode, "section", "activation-card");
  card.setAttribute("data-target", target.key);
  card.setAttribute("data-status", target.status);
  if (target.hook_health) {
    card.setAttribute("data-hook-health", target.hook_health);
  }
  const head = el(documentNode, "p", "activation-card-name", target.label);
  if (target.version) {
    head.appendChild(el(
      documentNode, "span", "activation-card-version", target.version,
    ));
  }
  card.appendChild(head);
  card.appendChild(el(
    documentNode, "p", "activation-card-status",
    harnessStatusLine(
      target.status, lastSeenDate(target.last_seen_at) || target.last_seen_at,
    ),
  ));
  return card;
}

export function renderHarnessTargets(documentNode, module, body) {
  const cards = el(documentNode, "div", "activation-cards");
  for (const target of module.targets || []) {
    cards.appendChild(harnessCard(documentNode, target));
  }
  body.appendChild(cards);
  for (const trustSurface of unapprovedTrustSurfaces(module.targets)) {
    body.appendChild(el(
      documentNode, "p", "activation-remediation",
      hookTrustRemediation(trustSurface),
    ));
  }
}
