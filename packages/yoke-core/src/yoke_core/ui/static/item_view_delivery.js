// How one item ships: the flow it is bound to, and every release that has
// carried it.
//
// An item page could say what the work is and never say whether it had
// shipped, so the reader went to Deployments and searched for the ref. The
// releases are read through the item itself, newest first, because the
// question is almost always "did the last one land".

import {
  buildUniverseRoute,
  deploymentRunHref,
} from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { callFunction, el, statePill } from "./universe_view_support.js";

function flowLine(documentNode, item) {
  const flowsHref = buildUniverseRoute(
    "deployments", String(item.project.id), "flows",
  );
  const line = el(documentNode, "div", "item-delivery-flow");
  if (item.deployment_flow) {
    line.appendChild(el(documentNode, "span", "item-delivery-label", "Flow"));
    const link = el(documentNode, "a", "mono", String(item.deployment_flow));
    link.href = flowsHref;
    line.appendChild(link);
    return line;
  }
  // No selection on the item is not "no flow": the project default for its
  // workflow applies, and saying which one that is belongs to the workflow's
  // own mechanics rather than to a guess made here.
  line.appendChild(el(documentNode, "span", "item-delivery-label", "Flow"));
  const fallback = el(
    documentNode, "a", "item-delivery-default",
    "none selected on this item — its workflow's project default applies",
  );
  fallback.href = flowsHref;
  line.appendChild(fallback);
  return line;
}

function deliveryRow(documentNode, item, run) {
  const row = el(documentNode, "div", "item-delivery-run");
  const link = el(documentNode, "a", "mono", String(run.id));
  link.href = deploymentRunHref(item.project.id, run.id);
  row.appendChild(link);
  const pill = statePill(documentNode, run.status, run.status);
  if (pill) row.appendChild(pill);
  if (run.current_stage) {
    row.appendChild(el(
      documentNode, "span", "item-delivery-stage", String(run.current_stage),
    ));
  }
  if (run.created_at) {
    row.appendChild(el(
      documentNode,
      "span",
      "item-delivery-when",
      relativeAgePhrase(run.created_at),
    ));
  }
  return row;
}

// Newest first. A run with no timestamp sorts last rather than being dropped:
// the record of the delivery is the fact, its ordering is the convenience.
function newestFirst(rows) {
  return [...rows].sort((left, right) => String(right.created_at || "")
    .localeCompare(String(left.created_at || "")));
}

export function itemDeliveryPanel(context, item) {
  const documentNode = context.document;
  const { panel, body } = workflowPanel(documentNode, "Delivery");
  body.appendChild(flowLine(documentNode, item));
  const runs = el(documentNode, "div", "item-delivery-runs", "loading releases…");
  body.appendChild(runs);
  (async () => {
    let result = null;
    try {
      const read = await callFunction(
        context.client, "deployment_runs.find_by_item", {},
        {
          kind: "item",
          public_ref: String(item.public_ref),
          project_id: String(item.project.id),
        },
      );
      if (read.status === 200 && read.envelope.success) {
        result = read.envelope.result || {};
      }
    } catch {
      result = null;
    }
    if (!context.isMounted()) return;
    if (!result) {
      runs.replaceChildren(el(
        documentNode,
        "p",
        "item-muted",
        "Releases for this item could not be read.",
      ));
      return;
    }
    const rows = newestFirst(result.rows || []);
    if (!rows.length) {
      runs.replaceChildren(el(
        documentNode, "p", "item-muted", "No release has carried this item.",
      ));
      return;
    }
    runs.replaceChildren(...rows.map((run) => deliveryRow(documentNode, item, run)));
  })();
  return panel;
}
