import { el } from "./universe_view_support.js";

const STAGE_STATES = new Set([
  "complete", "active", "pending", "failed", "stopped",
]);

function stageState(stage) {
  const state = String(stage?.state || "pending");
  return STAGE_STATES.has(state) ? state : "pending";
}

export function renderStageStrip(documentNode, stageRows) {
  const stages = Array.isArray(stageRows) ? stageRows : [];
  const strip = el(documentNode, "span", "delivery-run-stages");
  strip.setAttribute("role", "img");
  strip.setAttribute(
    "aria-label",
    stages.length
      ? `stages: ${stages.map((stage) => {
        const name = String(stage?.name || "unnamed");
        const failure = String(stage?.failure || "").trim();
        return [name, stageState(stage), failure].filter(Boolean).join(" ");
      }).join(", ")}`
      : "no stages published",
  );
  for (const stage of stages) {
    const state = stageState(stage);
    const segment = el(documentNode, "span", "delivery-run-stage");
    segment.setAttribute("data-state", state);
    segment.setAttribute(
      "title", `${String(stage?.name || "unnamed")} · ${state}`,
    );
    strip.appendChild(segment);
  }
  return strip;
}

export function stageFailureLabel(stageRows) {
  const failed = (Array.isArray(stageRows) ? stageRows : []).find(
    (stage) => stageState(stage) === "failed",
  );
  if (!failed) return "";
  const name = String(failed.name || "unnamed");
  const failure = String(failed.failure || "failed").trim() || "failed";
  return `${name} · ${failure}`;
}
