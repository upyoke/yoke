// The Overview's header chrome: the section roster, the live-signal stat
// tiles, the shared masthead, and the keyboard-accessible section jump
// strip. Split beside universe_views_overview.js so the composition module
// stays focused on wiring reads to panels; nothing here fetches — every
// number arrives through a tile's set() from the section loaders.

import { el } from "./universe_view_support.js";

// The prototype turns the board's section headings into a compact map of the
// page. Keep the labels and order beside the renderer so the jump strip cannot
// drift from the summaries it navigates.
export const OVERVIEW_SECTIONS = [
  ["strategy", "❖", "Strategy", "direction and recent strategy"],
  ["frontier", "⚡", "Frontier", "what can run now, and why"],
  ["sessions", "◈", "Sessions", "who is working"],
  ["delivery", "⬈", "Delivery", "what is shipping"],
  ["events", "≋", "Events", "the pulse · newest first"],
  ["doctor", "♥", "Doctor", "the floor · current health"],
];

// One stat tile that fills in when its read resolves. Until then — and if the
// read fails — it holds an em dash, never a zero that reads as a real count.
export function statTile(documentNode, label, signal) {
  const tile = el(documentNode, "div", "stat");
  tile.setAttribute("data-signal", signal);
  const number = el(documentNode, "div", "n", "—");
  tile.appendChild(number);
  tile.appendChild(el(documentNode, "div", "l", label));
  return {
    node: tile,
    set: (value) => {
      number.textContent =
        value === null || value === undefined ? "—" : String(value);
    },
  };
}

// The prototype gives the first live signals one shared masthead instead of
// leaving four unrelated tiles floating between navigation and content. This
// keeps the same honest values while restoring the page's visual hierarchy.
export function signalMasthead(documentNode, statRow) {
  const masthead = el(documentNode, "section", "overview-masthead");
  const heading = el(documentNode, "div", "overview-masthead-heading");
  heading.appendChild(el(documentNode, "strong", null, "Live signals"));
  heading.appendChild(el(
    documentNode, "span", null,
    "what can run, who is working, and whether the floor holds",
  ));
  masthead.appendChild(heading);
  masthead.appendChild(statRow);
  return masthead;
}

// A keyboard-accessible section map that stays available while the long
// Overview scrolls. Buttons scroll within this view; the panel-foot links keep
// owning navigation into the full destination screens.
export function sectionJumps(documentNode, panels) {
  const nav = el(documentNode, "nav", "overview-jumps");
  nav.setAttribute("aria-label", "Overview sections");
  for (const [view, icon, label] of OVERVIEW_SECTIONS) {
    const panel = panels.get(view);
    const button = el(
      documentNode, "button", "overview-jump", `${icon} ${label}`,
    );
    button.type = "button";
    button.setAttribute("aria-controls", `overview-${view}`);
    button.addEventListener("click", () => {
      if (typeof panel.scrollIntoView === "function") {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
    nav.appendChild(button);
  }
  return nav;
}
