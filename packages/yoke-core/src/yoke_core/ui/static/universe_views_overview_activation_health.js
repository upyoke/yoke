// Overview harness-health chrome: chips, colours, and orange remediation.
// Extracted so the activation renderer stays under the authored-file cap.

import { el } from "./universe_view_support.js";
import { hookTrustRemediation } from "./universe_views_overview_activation_copy.js";

const HEALTH_GREEN = "green";
const HEALTH_ORANGE = "orange";
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

export function renderHarnessTargets(documentNode, module, body) {
  const targets = el(documentNode, "p", "activation-targets");
  (module.targets || []).forEach((target, index) => {
    if (index) {
      targets.appendChild(el(documentNode, "span", "activation-target-sep", " · "));
    }
    const lit = Boolean(target.hit) && (
      !target.hook_health || target.hook_health === HEALTH_GREEN
    );
    const lastSeen = target.hook_health === HEALTH_ORANGE
      ? lastSeenDate(target.last_seen_at) : null;
    const label = [
      `${target.label}${lit ? " ✓" : ""}`,
      ...(lastSeen ? [`last seen ${lastSeen}`] : []),
    ].join(" · ");
    const chip = el(
      documentNode,
      "span",
      "activation-target",
      label,
    );
    chip.setAttribute("data-hit", String(Boolean(target.hit)));
    if (target.hook_health) {
      chip.setAttribute("data-hook-health", target.hook_health);
    }
    targets.appendChild(chip);
  });
  body.appendChild(targets);
  for (const trustSurface of unapprovedTrustSurfaces(module.targets)) {
    body.appendChild(el(
      documentNode, "p", "activation-remediation",
      hookTrustRemediation(trustSurface),
    ));
  }
}
