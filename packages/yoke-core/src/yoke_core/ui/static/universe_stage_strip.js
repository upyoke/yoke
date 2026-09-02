import { el } from "./universe_view_support.js";

const STAGE_STATES = new Set([
  "complete", "active", "pending", "failed", "stopped",
]);

function stageParts(stage) {
  const state = String(stage?.state || "pending");
  return {
    state: STAGE_STATES.has(state) ? state : "pending",
    name: String(stage?.name || "unnamed"),
    failure: String(stage?.failure || "").trim(),
  };
}

export function renderStageStrip(documentNode, stageRows) {
  const stages = (Array.isArray(stageRows) ? stageRows : []).map(stageParts);
  const strip = el(documentNode, "span", "delivery-run-stages");
  strip.setAttribute("role", "img");
  strip.setAttribute(
    "aria-label",
    stages.length
      ? `stages: ${stages.map(
        ({ name, state, failure }) => [name, state, failure]
          .filter(Boolean).join(" "),
      ).join(", ")}`
      : "no stages published",
  );
  for (const { name, state, failure } of stages) {
    const segment = el(documentNode, "span", "delivery-run-stage");
    segment.setAttribute("data-state", state);
    // The segment carries its own failure, so the strip says it in place
    // rather than under a second line of red text repeating the stage name.
    segment.setAttribute("title", `${name} · ${failure || state}`);
    strip.appendChild(segment);
  }
  return strip;
}
