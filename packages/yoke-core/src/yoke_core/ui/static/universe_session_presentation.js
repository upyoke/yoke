import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

export function presentationLabel(row) {
  if (row.presentation_state === "not-attached") return "local only";
  if (
    row.presentation_state !== "attached"
    || row.presentation_surface !== "remote-control"
  ) return "";
  const mode = row.presentation_mode === "bidirectional"
    ? "bidirectional"
    : row.presentation_mode === "outbound-only" ? "outbound only" : "mode unknown";
  return `Remote Control · ${mode}`;
}

export function appendSessionPresentation(documentNode, body, row) {
  const label = presentationLabel(row);
  if (!label) return;
  const line = el(
    documentNode,
    "div",
    "session-presentation",
    `Presentation: ${label}`,
  );
  attachTooltip(
    documentNode, line,
    "Observed attachment only; initiating authority and frontend are unknown.",
  );
  body.appendChild(line);
}

// Two short statuses, held apart because they answer different questions: the
// release carrying this session's item, and where that item is in its own
// workflow. Folded together they read as one state and hide the common case
// where an item is fine and its release is not.
const RUN_STATE_LABELS = {
  created: "not started",
  executing: "running",
  succeeded: "done",
  failed: "stopped",
  cancelled: "cancelled",
};

function activeStageName(stages) {
  const active = (stages || []).find((stage) => stage.state === "active")
    || (stages || []).find((stage) => stage.state === "failed");
  return active ? String(active.name) : "";
}

export function deliveryStatusLabels(row) {
  const labels = [];
  const delivery = row.primary_item_delivery;
  if (delivery?.run_id) {
    const state = RUN_STATE_LABELS[delivery.status] || String(delivery.status || "");
    labels.push({
      key: "run",
      text: `Run: ${[delivery.stage, state].filter(Boolean).join(" · ")}`,
    });
  }
  const stage = activeStageName(row.primary_item_stages);
  if (stage) labels.push({ key: "item", text: `Item: ${stage}` });
  return labels;
}

export function appendSessionDeliveryStatus(documentNode, body, row) {
  const labels = deliveryStatusLabels(row);
  if (!labels.length) return;
  const line = el(documentNode, "div", "session-delivery");
  for (const label of labels) {
    line.appendChild(el(
      documentNode, "span", `session-delivery-pill is-${label.key}`, label.text,
    ));
  }
  body.appendChild(line);
}
