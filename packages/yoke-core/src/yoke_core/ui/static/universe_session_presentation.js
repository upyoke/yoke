import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

// Who is running this session, as the one mark and label every surface that
// shows a session uses: the roster card, the claimant preview on an item, the
// deploy-lock holder on a run card. A CI runner is a machine rather than a
// harness, and says so.
export function harnessIdentity(row) {
  const executor = String(row.executor_surface || row.executor || "unreported");
  const normalized = executor.toLowerCase();
  if (row.actor_kind === "system" && normalized.includes("ci")) {
    return { mark: "\u2699", className: "h-machine", label: executor };
  }
  if (row.executor_mark && row.executor_class_name) {
    return {
      mark: row.executor_mark,
      className: row.executor_class_name,
      label: executor,
    };
  }
  return {
    mark: executor.slice(0, 1).toUpperCase() || "?",
    className: "h-other",
    label: executor,
  };
}

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
  // The item half is this member's standing at the item QA stage answering
  // for it now. The pill carries the state itself — "awaiting review" and
  // "rejected" are different waits and a reader on a phone has to be able to
  // tell them apart without hovering. Which stage, and the sentence behind
  // the state, ride as the title for whoever wants the detail.
  if (delivery.item_qa) {
    labels.push({
      key: "item",
      text: `Item QA: ${delivery.item_qa}`,
      // Only a blocked state has anything further to say; an accepted one
      // would otherwise carry a tooltip repeating a stage name.
      detail: delivery.item_qa_reason
        ? [delivery.item_qa_stage, delivery.item_qa_reason]
          .filter(Boolean).join(": ")
        : "",
    });
  }
  return labels;
}

export function appendSessionDeliveryStatus(documentNode, body, row) {
  const labels = deliveryStatusLabels(row);
  if (!labels.length) return;
  const line = el(documentNode, "div", "session-delivery");
  for (const label of labels) {
    const pill = el(
      documentNode, "span", `session-delivery-pill is-${label.key}`, label.text,
    );
    if (label.detail) pill.setAttribute("title", label.detail);
    line.appendChild(pill);
  }
  body.appendChild(line);
}
