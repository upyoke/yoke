// What the content area holds while the app is still resolving what to draw
// there. One small line, not a skeleton: the shell around it is already real
// — navigation, header, footer — so the honest missing piece is this one
// region, and a block of grey placeholder shapes would claim a layout the
// app does not know yet.
//
// It appears immediately and with no minimum lifetime. A threshold before
// showing it leaves the observed frame — a fully drawn shell over an empty
// area — exactly as it was, and a minimum lifetime holds content back that
// has already arrived.

import { el } from "./universe_view_support.js";

export function routeLoadingLine(documentNode) {
  const line = el(documentNode, "div", "route-loading", "Loading…");
  // Announced rather than described: a reader arriving mid-load is told the
  // region is working, and `aria-busy` marks the region itself so the
  // announcement is not mistaken for the content.
  line.setAttribute("role", "status");
  line.setAttribute("aria-busy", "true");
  return line;
}
