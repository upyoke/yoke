import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";
import { renderStageStrip } from "./universe_stage_strip.js";

function enabled(value) {
  return value === true || value === 1 || value === "1" || value === "true";
}

// The frontier leads with Frozen when both item flags are set. Keep the
// pills in that order and give the stage strip the same leading color.
export function itemConditions(item) {
  const frozen = enabled(item?.item_frozen);
  const blocked = enabled(item?.item_blocked);
  return [
    ...(frozen ? [{ name: "Frozen", tone: "frozen" }] : []),
    ...(blocked ? [{ name: "Blocked", tone: "blocked" }] : []),
  ];
}

export function appendItemConditionPills(documentNode, work, item) {
  for (const condition of itemConditions(item)) {
    const pill = el(
      documentNode, "span", `session-item-condition is-${condition.tone}`,
      condition.name,
    );
    const reason = String(item?.item_blocked_reason || "").trim();
    if (reason) attachTooltip(documentNode, pill, reason);
    work.appendChild(pill);
  }
}

export function appendItemStageProgress(documentNode, work, stages, item) {
  if (!Array.isArray(stages) || !stages.length) return;
  const progress = el(documentNode, "div", "session-item-stage-progress");
  const strip = renderStageStrip(documentNode, stages);
  const condition = itemConditions(item)[0];
  if (condition) {
    let current = stages.findIndex((stage) => stage.state === "active");
    if (current < 0) current = stages.findLastIndex((stage) => stage.state === "failed");
    if (current >= 0) {
      const segment = strip.children[current];
      segment.setAttribute("data-item-condition", condition.tone);
      attachTooltip(
        documentNode, segment,
        `${segment.getAttribute("data-tooltip")} · ${condition.name}`,
      );
      strip.setAttribute(
        "aria-label", `${strip.getAttribute("aria-label")}; item ${condition.name.toLowerCase()}`,
      );
    }
  }
  progress.appendChild(strip);
  work.appendChild(progress);
}
