// The Waiting graph's model, built from the bands' own rows and the
// dependency edges frontier.list serves. Every Frontier item is a node in
// the band it was drawn in; an edge end the page does not otherwise show
// becomes a ghost carrying the stage and title the edge row brought with it.

import { frontierIndex } from "./frontier_dependency_model.js";
import { reference } from "./frontier_band_rows.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { relativeAgePhrase } from "./universe_time.js";

function href(projectId, projectSequence, publicRef) {
  return itemDrillInHref({ projectId, projectSequence, publicRef }) || "";
}

function age(label, timestamp) {
  return timestamp ? `${label} ${relativeAgePhrase(timestamp)}` : "";
}

function rowNode(row, band, extra = {}) {
  const ref = reference(row);
  return {
    ref,
    band,
    stage: String(row.stage_label || row.status || band),
    title: String(row.title || ""),
    href: href(row.project_id, row.project_sequence, ref),
    projectId: row.project_id,
    project: row.project,
    terminal: Boolean(row.terminal),
    ...extra,
  };
}

function edgeOf(row) {
  return {
    from: row.blocking_item,
    to: row.dependent_item,
    gate: row.gate_point,
    sat: row.satisfaction,
    why: row.rationale || "",
    env: row.environment || null,
    blockerFacts: {
      stage: row.blocking_stage,
      title: row.blocking_title,
      terminal: row.blocking_terminal,
      projectId: row.blocking_project_id,
      href: href(row.blocking_project_id, row.blocking_project_sequence, row.blocking_item),
    },
  };
}

/**
 * The indexed model for every band's rows and the served edges.
 *
 * `deploy(row)` answers an item's one-line delivery state, or "" while the
 * run roster has not settled.
 */
export function frontierGraphModel(bandRows, edgeRows, deploy) {
  const nodes = new Map();
  const put = (node) => { if (!nodes.has(node.ref)) nodes.set(node.ref, node); };
  for (const { row, reason } of bandRows.waiting) {
    const dependency = reason.flag.tone === "dependency";
    put(rowNode(row, "waiting", {
      age: age("filed", row.created_at),
      held: dependency ? null : reason.flag.label,
    }));
  }
  for (const { row } of bandRows.active) {
    put(rowNode(row, "active", { age: age("updated", row.updated_at) }));
  }
  for (const row of bandRows.ready) {
    put(rowNode(row, "ready", { age: age("filed", row.created_at) }));
  }
  for (const row of bandRows.releasing) {
    put(rowNode(row, "release", { age: age("updated", row.updated_at), deploy: deploy(row) }));
  }
  for (const row of bandRows.done) {
    put(rowNode(row, "done", { age: age("finished", row.finished_at), deploy: deploy(row) }));
  }
  const edges = edgeRows.map(edgeOf);
  for (const row of edgeRows) {
    if (nodes.has(row.dependent_item)) continue;
    nodes.set(row.dependent_item, {
      ref: row.dependent_item,
      band: "off",
      stage: "not on this Frontier",
      title: "",
      terminal: false,
      projectId: row.dependent_project_id,
      href: href(row.dependent_project_id, row.dependent_project_sequence, row.dependent_item),
    });
  }
  return frontierIndex(nodes, edges);
}
