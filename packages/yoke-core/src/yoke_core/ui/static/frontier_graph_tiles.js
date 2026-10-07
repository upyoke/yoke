// What the Waiting graph draws for one item: its tile, and the detail panel a
// pinned tile opens. A tile is a selectable region holding a real link (the
// item number) and, when someone holds the item, its session chip — so it is
// a `div role=button`, never a button.

import {
  FRONTIER_GATE,
  frontierCondition,
  frontierEdgeDeploy,
  frontierNever,
  frontierTileMeta,
} from "./frontier_dependency_model.js";
import { el } from "./universe_view_support.js";

/**
 * One compact tile.
 *
 * `helpers.claimantFor(ref)` returns the item's session chip row, or null
 * when nobody holds it.
 */
export function frontierTile(documentNode, model, ref, helpers) {
  const node = model.nodes.get(ref);
  const tile = el(documentNode, "div", "fdv-tile");
  tile.tabIndex = 0;
  tile.setAttribute("role", "button");
  tile.setAttribute("data-fdv-ref", ref);
  tile.setAttribute("data-band", node.band);
  if (model.critical.has(ref)) tile.classList.add("is-critical");
  if (node.stall) tile.classList.add("is-stall");
  else if (node.stuck) tile.classList.add("is-stuck");
  if (node.band === "off") tile.classList.add(node.terminal ? "is-dead" : "is-ghost");
  const head = el(documentNode, "span", "fdv-tile-head");
  const link = el(documentNode, "a", "fdv-tile-ref", ref);
  link.href = node.href;
  head.appendChild(link);
  head.appendChild(el(
    documentNode, "span", "fdv-tile-stage", node.held && !node.stall ? node.held : node.stage,
  ));
  if (node.unblocks) {
    head.appendChild(el(documentNode, "span", "fdv-unblocks", `unblocks ${node.unblocks}`));
  }
  if (node.age) head.appendChild(el(documentNode, "span", "fdv-tile-age", node.age));
  tile.appendChild(head);
  tile.appendChild(el(
    documentNode, "span", "fdv-tile-title", node.title || "Open the item for its title and state",
  ));
  const meta = frontierTileMeta(node);
  if (meta) tile.appendChild(el(documentNode, "span", "fdv-tile-meta", meta));
  const why = node.blockers.filter((e) => e.why).map((e) => `${e.from}: ${e.why}`);
  if (why.length) tile.title = why.join("\n");
  const chip = helpers.claimantFor(ref);
  if (chip) tile.appendChild(chip);
  return tile;
}

/**
 * The detail panel's contents for one pinned item, top to bottom: its stuck
 * reason, every blocker, every dependent, then its full production card.
 *
 * `helpers.cardFor(ref)` returns that card, or null for an item that is not
 * on this Frontier; `onTrace(ref)` selects the item a row names.
 */
export function frontierDetail(documentNode, model, ref, helpers, onTrace) {
  const n = model.nodes.get(ref);
  const out = [];
  if (n.stuck) out.push(el(documentNode, "p", "fdv-detail-alert", n.stuck));
  const list = (title, edges, side) => {
    if (!edges.length) return;
    out.push(el(documentNode, "h4", "fdv-detail-h", title));
    const ul = el(documentNode, "ul", "fdv-detail-list");
    for (const e of edges) {
      const other = model.nodes.get(side === "up" ? e.from : e.to);
      // The row traces that item; its number is a link to the item itself.
      const li = el(documentNode, "li");
      li.setAttribute("data-action", "fdv-select");
      li.setAttribute("data-fdv-target", other.ref);
      const go = el(documentNode, "a", "fdv-tile-ref", other.ref);
      go.href = other.href;
      li.appendChild(go);
      li.appendChild(el(documentNode, "span", "fdv-gate", `blocks ${FRONTIER_GATE[e.gate]}`));
      const never = frontierNever(e, model.nodes.get(e.from));
      const deploy = other.deploy || frontierEdgeDeploy(e);
      li.appendChild(el(documentNode, "span", "fdv-detail-copy", side === "up"
        ? `until it ${frontierCondition(e.sat)} · now ${other.stage}${deploy ? ` · ${deploy}` : ""}${never ? ` — ${never}` : ""}`
        : `${other.title || ""}`));
      if (e.why) li.appendChild(el(documentNode, "span", "fdv-detail-why", e.why));
      li.addEventListener("click", (event) => {
        if (event.target?.closest?.("a")) return;
        onTrace(other.ref);
      });
      ul.appendChild(li);
    }
    out.push(ul);
  };
  list(`Waiting on ${n.blockers.length}`, n.blockers, "up");
  list(`Holding back ${n.dependents.length}`, n.dependents, "down");
  out.push(helpers.cardFor(ref)
    || el(documentNode, "p", "fdv-detail-empty", `${ref} is ${n.stage} and is not on this Frontier.`));
  return out;
}
