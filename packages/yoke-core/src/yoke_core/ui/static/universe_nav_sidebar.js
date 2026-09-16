// The sidebar's destination list: one row per destination, grouped, with the
// drawer group an operator can close.
//
// Two things here are not decoration. A group marked collapsible is a real
// disclosure — its heading is the control, it says whether it is expanded,
// and the answer is remembered against the person rather than the tab. And
// absence is the only thing that means closed: a group nobody has touched
// starts closed, while one the operator opened stays open on the next visit,
// on the next machine, in the next browser.

import { NAV_ICONS } from "./universe_nav_icons.js";
import { NAV, NAV_GROUPS } from "./universe_navigation.js";

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// The marking beside a destination. Markup rather than a glyph because these
// are outline drawings: they inherit `currentColor`, so a row's active and
// hover colours carry the icon with them.
export function navIcon(documentNode, viewId) {
  const slot = el(documentNode, "span", "ico");
  const markup = NAV_ICONS[viewId];
  if (markup) slot.innerHTML = markup;
  return slot;
}

function navRow(documentNode, entry) {
  const link = el(documentNode, "a", "nav-link");
  link.appendChild(navIcon(documentNode, entry.id));
  link.appendChild(el(documentNode, "span", "txt", entry.label));
  return link;
}

// A collapsible group: heading as the control, destinations in one region
// the heading names. The heading keeps the plain group styling — no
// disclosure triangle is added, because the row is already a control and the
// marker would be a second thing saying so.
function collapsibleGroup(documentNode, group, host, onToggle) {
  const heading = el(documentNode, "div", "nav-group", group.label);
  heading.setAttribute("role", "button");
  heading.tabIndex = 0;
  heading.id = `universe-nav-group-${group.id}`;
  const items = el(documentNode, "div", "nav-group-items");
  items.id = `universe-nav-group-items-${group.id}`;
  heading.setAttribute("aria-controls", items.id);
  host.appendChild(heading);
  host.appendChild(items);

  let open = false;
  const paint = () => {
    heading.setAttribute("aria-expanded", String(open));
    items.hidden = !open;
  };
  const toggle = () => {
    open = !open;
    paint();
    onToggle(group.id, open);
  };
  heading.addEventListener("click", toggle);
  heading.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggle();
  });
  paint();
  return {
    items,
    setOpen(next) {
      open = Boolean(next);
      paint();
    },
  };
}

// Build the whole list. `resolvedSections` decides whether a host-fed
// destination exists at all: a local universe has no Members or Billing, and
// a heading over nothing is a heading that lies.
export function buildSidebarNavigation({
  documentNode,
  navEl,
  resolvedSections,
  onGroupToggle,
}) {
  const navLinks = new Map();
  const collapsible = new Map();
  for (const group of NAV_GROUPS) {
    const entries = NAV.filter((entry) => (
      entry.group === group.id
      && !entry.hidden
      && !(entry.hostFed && !resolvedSections[entry.id])
    ));
    if (!entries.length) continue;
    let host = navEl;
    if (group.label && group.collapsible) {
      const drawer = collapsibleGroup(
        documentNode, group, navEl, onGroupToggle,
      );
      collapsible.set(group.id, drawer);
      host = drawer.items;
    } else if (group.label) {
      navEl.appendChild(el(documentNode, "div", "nav-group", group.label));
    }
    for (const entry of entries) {
      const link = navRow(documentNode, entry);
      navLinks.set(entry.id, link);
      host.appendChild(link);
    }
  }
  return {
    navLinks,
    // Apply the remembered state once it lands. A group the operator never
    // touched is absent from `groups` and keeps its closed default.
    applyRememberedGroups(groups) {
      for (const [groupId, drawer] of collapsible) {
        if (typeof groups?.[groupId] === "boolean") {
          drawer.setOpen(groups[groupId]);
        }
      }
    },
  };
}
