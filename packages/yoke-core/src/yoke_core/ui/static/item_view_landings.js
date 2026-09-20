// Every landing an item has made, oldest first.
//
// The item page said "merged" once, from its status, and an item that landed
// four times in one day read exactly like one that landed once. Each row here
// is a landing of its own: the merge it landed under, the pull request that
// carried it, when it happened, and which release delivered it — or that none
// has, which is a fact rather than a silence.
//
// An item with one landing shows one row and no comparison. The panel is
// absent entirely until a landing exists, so work that has not merged gains
// nothing to read past.

import { deploymentRunHref } from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import { workflowPanel } from "./workflow_view_primitives.js";
import { callFunction, el } from "./universe_view_support.js";

// Enough of a commit to name it in a repository, short enough that a landing
// reads as one line.
const SHA_WIDTH = 12;

// What each route means to a reader, who should not have to know which engine
// merged to understand what happened to the branch.
const ROUTE_LABELS = {
  merge_queue: "merge queue",
  standalone: "merge",
  fast_forward: "fast-forward",
};

function shortSha(sha) {
  return String(sha || "").slice(0, SHA_WIDTH);
}

function deliveryNode(documentNode, item, landing) {
  const delivery = landing.delivery || {};
  const runId = String(delivery.run_id || "").trim();
  if (!runId) {
    return el(
      documentNode, "span", "item-landing-undelivered", "not delivered",
    );
  }
  const link = el(documentNode, "a", "mono item-landing-release", runId);
  link.href = deploymentRunHref(item.project.id, runId);
  return link;
}

function landingRow(documentNode, item, landing, ordinal) {
  const row = el(documentNode, "div", "item-landing");
  row.appendChild(el(
    documentNode, "span", "item-landing-ordinal", `#${ordinal}`,
  ));
  const merge = el(
    documentNode, "span", "mono item-landing-merge", shortSha(landing.merge_sha),
  );
  // The full sha on hover: the row names a landing, and an auditor settling
  // which merge it was needs the whole thing without leaving the page.
  merge.title = String(landing.merge_sha || "");
  row.appendChild(merge);
  row.appendChild(el(
    documentNode,
    "span",
    "item-landing-route",
    ROUTE_LABELS[String(landing.route || "")] || String(landing.route || ""),
  ));
  const prNumber = String(landing.pr_number || "").trim();
  if (prNumber) {
    row.appendChild(el(
      documentNode, "span", "mono item-landing-pr", `#${prNumber}`,
    ));
  }
  if (landing.landed_at) {
    row.appendChild(el(
      documentNode,
      "span",
      "item-landing-when",
      relativeAgePhrase(landing.landed_at),
    ));
  }
  row.appendChild(deliveryNode(documentNode, item, landing));
  return row;
}

export function itemLandingsPanel(context, item) {
  const documentNode = context.document;
  const { panel, body } = workflowPanel(documentNode, "Landings");
  panel.className += " item-landings-panel";
  // Hidden until the read answers: an item that never landed should not draw
  // a panel saying so, and one that landed should not flash "none".
  panel.hidden = true;
  (async () => {
    let result = null;
    try {
      const read = await callFunction(
        context.client, "item_landings.list", {},
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
      // A read that failed is not an item that never landed, and saying so
      // is the difference between "nothing happened" and "ask again".
      panel.hidden = false;
      body.replaceChildren(el(
        documentNode,
        "p",
        "item-muted",
        "Landings for this item could not be read.",
      ));
      return;
    }
    const rows = result.rows || [];
    if (!rows.length) return;
    panel.hidden = false;
    body.replaceChildren(...rows.map(
      (landing, index) => landingRow(documentNode, item, landing, index + 1),
    ));
  })();
  return panel;
}
