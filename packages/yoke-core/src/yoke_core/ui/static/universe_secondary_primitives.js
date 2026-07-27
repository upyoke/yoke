// Small presentation primitives shared by the secondary universe screens.

import { el, statePill } from "./universe_view_support.js";

export function metricStrip(documentNode, metrics) {
  const strip = el(documentNode, "div", "metric-strip");
  for (const metric of metrics) {
    const node = el(documentNode, "div", "metric");
    node.setAttribute("data-tone", metric.tone || "neutral");
    node.appendChild(el(documentNode, "strong", null, String(metric.value ?? 0)));
    node.appendChild(el(documentNode, "span", null, metric.label));
    strip.appendChild(node);
  }
  return strip;
}

export function workflowBadge(documentNode, workflow, version = null) {
  const suffix = version === null || version === undefined || version === ""
    ? "" : ` · v${version}`;
  return el(
    documentNode,
    "span",
    "workflow-badge",
    `${workflow || "workflow"}${suffix}`,
  );
}

export function stageProgress(
  documentNode,
  index,
  count,
  label,
) {
  const wrap = el(documentNode, "div", "stage-progress");
  const normalizedIndex = Number(index);
  const normalizedCount = Number(count);
  const current = Number.isFinite(normalizedIndex) && normalizedIndex >= 0
    ? normalizedIndex + 1 : 0;
  const total = Number.isFinite(normalizedCount) && normalizedCount > 0
    ? normalizedCount : 0;
  const track = el(documentNode, "span", "stage-progress-track");
  const progressLabel = total
    ? `stage ${current} of ${total}` : (label || "stage unavailable");
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", progressLabel);
  track.setAttribute("title", label || progressLabel);
  for (let stageIndex = 0; stageIndex < total; stageIndex += 1) {
    const segment = el(documentNode, "i", "stage-progress-segment");
    if (stageIndex < current) segment.classList.add("is-complete");
    track.appendChild(segment);
  }
  wrap.appendChild(track);
  wrap.appendChild(el(
    documentNode,
    "span",
    "stage-progress-label",
    total ? `${current}/${total}` : "—",
  ));
  return wrap;
}

export function deliveryStageBar(documentNode, stages) {
  const bar = el(documentNode, "div", "delivery-stage-bar");
  bar.setAttribute("aria-label", "Run stages");
  for (const stage of stages || []) {
    const segment = el(documentNode, "span", "delivery-stage");
    const state = String(stage.state || "pending");
    segment.setAttribute("data-state", state);
    segment.setAttribute("title", `${stage.name} · ${state}`);
    segment.appendChild(el(documentNode, "i"));
    segment.appendChild(el(documentNode, "span", null, stage.name));
    bar.appendChild(segment);
  }
  return bar;
}

export function labelledFact(documentNode, label, value, className = null) {
  const fact = el(documentNode, "div", `labelled-fact${className ? ` ${className}` : ""}`);
  fact.appendChild(el(documentNode, "span", "labelled-fact-label", label));
  if (value && typeof value === "object" && value.tagName) {
    fact.appendChild(value);
  } else {
    fact.appendChild(el(
      documentNode,
      "span",
      "labelled-fact-value",
      String(value ?? "—"),
    ));
  }
  return fact;
}

export function statusWithLabel(documentNode, state, label = state) {
  return statePill(documentNode, state, label);
}
