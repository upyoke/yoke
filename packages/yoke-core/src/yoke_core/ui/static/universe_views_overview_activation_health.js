// Overview harness-health chrome: chips, colours, and orange remediation.
// Extracted so the activation renderer stays under the authored-file cap.

import { el } from "./universe_view_support.js";
import { hookTrustRemediation } from "./universe_views_overview_activation_copy.js";

const HEALTH_ORANGE = "orange";

function orangeTrustSurfaces(targets) {
  const surfaces = [];
  for (const target of targets || []) {
    if (target.hook_health !== HEALTH_ORANGE || !target.trust_surface) continue;
    if (!surfaces.includes(target.trust_surface)) {
      surfaces.push(target.trust_surface);
    }
  }
  return surfaces;
}

export function renderHarnessTargets(documentNode, module, body) {
  const targets = el(documentNode, "p", "activation-targets");
  (module.targets || []).forEach((target, index) => {
    if (index) {
      targets.appendChild(el(documentNode, "span", "activation-target-sep", " · "));
    }
    const chip = el(documentNode, "span", "activation-target", target.label);
    chip.setAttribute("data-hit", String(Boolean(target.hit)));
    if (target.hook_health) {
      chip.setAttribute("data-hook-health", target.hook_health);
    }
    targets.appendChild(chip);
  });
  body.appendChild(targets);
  for (const trustSurface of orangeTrustSurfaces(module.targets)) {
    body.appendChild(el(
      documentNode, "p", "activation-remediation",
      hookTrustRemediation(trustSurface),
    ));
  }
}
