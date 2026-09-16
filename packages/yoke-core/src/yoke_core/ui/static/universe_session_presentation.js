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
// release carrying this session's item, and what that item's own QA inside
// that release found. Folded together they read as one state and hide the
// common case where an item is fine and its release is not.
//
// Both halves print the values the control plane stores. A run status and a
// QA outcome are enum values other surfaces gate on and search by, so a
// friendlier word here would be a vocabulary a reader cannot match against
// anything else — and "done" for `succeeded` or "stopped" for `failed` reads
// as a different fact, not a shorter one.
export function deliveryStatusLabels(row) {
  const labels = [];
  const delivery = row.primary_item_delivery;
  if (!delivery?.run_id) return labels;
  // The newest run is not automatically the one in flight: when every run
  // carrying this item is over, the card says which reading it is giving.
  const lead = delivery.live ? "Run" : "Last run";
  labels.push({
    key: "run",
    text: `${lead}: ${[delivery.stage, delivery.status].filter(Boolean).join(" · ")}`,
  });
  // The item half is this member's own QA inside that run. Its workflow stage
  // is a different fact, and the card's stage strip already draws it.
  if (delivery.item_qa) {
    labels.push({
      key: "item",
      text: `Item QA: ${String(delivery.item_qa).replaceAll("_", " ")}`,
    });
  }
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
