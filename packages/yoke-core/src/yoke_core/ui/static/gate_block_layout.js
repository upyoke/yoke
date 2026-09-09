// The small shared vocabulary a gate card is built from: a titled block, a
// code-and-copy line inside it, and the honest "+N more" that stops a long
// list from silently hiding what it did not draw.
//
// Both gate surfaces read from here so a release, a branch diff and an
// evidence stack are laid out identically, and the cap on how many entries a
// block lists is one number rather than one per caller.

import { el } from "./universe_view_support.js";

export const MAX_LISTED = 6;

export function block(documentNode, parent, className, heading) {
  const node = el(documentNode, "div", className);
  if (heading) node.appendChild(el(documentNode, "div", "gate-block-head", heading));
  parent.appendChild(node);
  return node;
}

export function row(documentNode, parent, code, copy) {
  const line = el(documentNode, "div", "gate-block-row");
  line.appendChild(el(documentNode, "code", "gate-block-code", code));
  if (copy) line.appendChild(el(documentNode, "span", "gate-block-copy", copy));
  parent.appendChild(line);
  return line;
}

export function overflow(documentNode, parent, total, noun) {
  if (total <= MAX_LISTED) return;
  parent.appendChild(el(
    documentNode,
    "div",
    "gate-block-more",
    `+${total - MAX_LISTED} more ${noun}`,
  ));
}

export const gateBlockLayout = { MAX_LISTED, block, overflow, row };
