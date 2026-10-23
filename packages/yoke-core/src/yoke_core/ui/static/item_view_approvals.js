// An item's work approvals: the request standing now, what it moves, who may
// decide it, and the answers before it.
//
// Each row is the same decision record a run card and the Inbox draw, and
// answering here goes through the one resolver they use, so an approval
// given on this page is the approval everywhere. ``standing`` is the
// server's reading of the request against the item as it is now: a request
// for a transition the item has left reads superseded and never offers an
// answer for work it no longer describes.

import { createDecisionResolver } from "./inbox_rows.js";
import { decisionList, resolvedDecisionRecord } from "./universe_run_gates.js";
import { relativeTime } from "./universe_time.js";
import { callFunction, el } from "./universe_view_support.js";
import { workflowPanel } from "./workflow_view_primitives.js";

const STANDING_COPY = {
  pending: "awaiting a decision",
  approved: "approved · not yet completed",
  rejected: "rejected",
  completed: "approved · completed",
  superseded: "superseded",
};

function transitionLine(documentNode, gate) {
  const facts = gate.subject_context || {};
  const line = el(documentNode, "p", "item-approval-transition",
    `${facts.from_stage || "?"} → ${facts.to_stage || "?"} · ${
      STANDING_COPY[gate.standing] || gate.status}`);
  if (gate.requested_at) {
    line.appendChild(documentNode.createTextNode(" · requested "));
    line.appendChild(relativeTime(documentNode, gate.requested_at));
  }
  return line;
}

function drawApprovals(context, body, approvals, onAct) {
  const documentNode = context.document;
  const [latest, ...older] = approvals;
  const current = latest && latest.standing !== "superseded" ? latest : null;
  const earlier = current ? older : approvals;
  const nodes = [];
  if (current) {
    nodes.push(transitionLine(documentNode, current));
    nodes.push(decisionList(context, [current], current.standing === "pending" ? onAct : null, {
      scope: "item",
    }));
  } else {
    nodes.push(el(documentNode, "p", "item-muted", "No approval is open for this item's current stage."));
  }
  if (earlier.length) {
    const history = el(documentNode, "div", "item-approval-history");
    history.appendChild(el(documentNode, "strong", null, "Earlier decisions"));
    for (const gate of earlier) {
      const entry = el(documentNode, "div", "item-approval-entry");
      entry.setAttribute("data-request-id", String(gate.request_id ?? ""));
      entry.appendChild(transitionLine(documentNode, gate));
      const record = resolvedDecisionRecord(documentNode, gate);
      if (record) entry.appendChild(record);
      history.appendChild(entry);
    }
    nodes.push(history);
  }
  body.replaceChildren(...nodes);
}

// ``null`` when no work approval was ever requested for this item, the way
// an unclaimed item has no claimant panel. A serving build that does not
// send ``approvals`` draws no panel rather than claiming there are none.
export function itemApprovalsPanel(context, item) {
  if (!Array.isArray(item.approvals) || !item.approvals.length) return null;
  const documentNode = context.document;
  const { panel, body } = workflowPanel(documentNode, "Approvals");
  const target = {
    kind: "item", public_ref: String(item.public_ref), project_id: String(item.project.id),
  };
  let onAct = null;
  const reload = async () => {
    const read = await callFunction(context.client, "items.detail.get", { include: [] }, target);
    if (!context.isMounted()) return;
    if (read.status !== 200 || !read.envelope.success) {
      body.appendChild(el(documentNode, "p", "inbox-row-error error",
        "The decision was recorded, but this list could not be refreshed. Reload the page to see it."));
      return;
    }
    drawApprovals(context, body, read.envelope.result?.item?.approvals || [], onAct);
  };
  const resolve = createDecisionResolver(context, reload);
  onAct = (gate, action, node, note) => resolve({ id: gate.request_id }, action, node, note);
  drawApprovals(context, body, item.approvals, onAct);
  return panel;
}
