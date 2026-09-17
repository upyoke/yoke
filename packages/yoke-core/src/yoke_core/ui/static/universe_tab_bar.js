// The one underlined tab strip. Tabs are facets of a single subject — never a
// second level of navigation — and every screen that shows them shows the same
// strip: the same underline, the same weights, and the same keyboard model.
//
// Two shapes, because a facet is addressed in one of two ways. A facet the
// route names is a link, so it is bookmarkable and opens in a new tab like any
// other destination. A facet that is local state is a button, and then the
// strip owns the roving tabindex and the arrow keys a tablist owes a keyboard
// operator. Three screens each grew their own version of this; they disagreed
// on the selected class, on whether arrows worked, and on whether the strip
// could scroll.

import { el } from "./universe_view_support.js";

function decorate(documentNode, node, tab, selected) {
  node.setAttribute("role", "tab");
  node.setAttribute("aria-selected", String(selected));
  if (tab.ariaLabel) node.setAttribute("aria-label", tab.ariaLabel);
  if (tab.controls) node.setAttribute("aria-controls", tab.controls);
  if (tab.domId) node.setAttribute("id", tab.domId);
  for (const [name, value] of Object.entries(tab.attributes || {})) {
    node.setAttribute(name, value);
  }
  if (tab.disabled) node.classList.add("is-disabled");
  // A status only earns a place on a tab when it is a reason to cross the
  // strip; the screen decides that, and hands the word over.
  for (const status of tab.statuses || []) {
    node.appendChild(el(
      documentNode, "span", `tab-link-status ${status.tone || ""}`.trim(),
      status.label,
    ));
  }
  return node;
}

function strip(documentNode, label) {
  const bar = el(documentNode, "div", "tab-bar");
  bar.setAttribute("role", "tablist");
  if (label) bar.setAttribute("aria-label", label);
  return bar;
}

function className(selected) {
  return `tab-link${selected ? " active" : ""}`;
}

// A facet the route names.
export function routeTabBar(documentNode, { label, tabs, activeId, hrefFor }) {
  const bar = strip(documentNode, label);
  for (const tab of tabs) {
    const selected = tab.id === activeId;
    const link = el(documentNode, "a", className(selected), tab.label);
    link.href = hrefFor(tab);
    bar.appendChild(decorate(documentNode, link, tab, selected));
  }
  return bar;
}

// A facet held in the screen's own state, painted into a strip the caller
// already holds. Selecting from the keyboard moves focus with the selection,
// which is what makes a roving tabindex navigable rather than merely correct.
export function paintTabBar(documentNode, bar, { tabs, activeId, onSelect }) {
  bar.replaceChildren();
  const focusTab = (index) => {
    const node = bar.children[index];
    if (typeof node?.focus === "function") node.focus();
  };
  for (const [index, tab] of tabs.entries()) {
    const selected = tab.id === activeId;
    const button = el(documentNode, "button", className(selected), tab.label);
    button.type = "button";
    button.tabIndex = selected ? 0 : -1;
    button.addEventListener("click", () => onSelect(tab.id));
    button.addEventListener("keydown", (event) => {
      const offsets = { ArrowLeft: -1, ArrowRight: 1 };
      let next = null;
      if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else if (Object.hasOwn(offsets, event.key)) {
        next = (index + offsets[event.key] + tabs.length) % tabs.length;
      }
      if (next === null) return;
      event.preventDefault?.();
      onSelect(tabs[next].id);
      focusTab(next);
      // The selection may repaint the strip, replacing the node just focused.
      Promise.resolve().then(() => focusTab(next));
    });
    bar.appendChild(decorate(documentNode, button, tab, selected));
  }
}

// The same, for a caller that wants the strip built for it.
export function stateTabBar(documentNode, { label, onSelect }) {
  const bar = strip(documentNode, label);
  return {
    bar,
    paint: (tabs, activeId) => paintTabBar(
      documentNode, bar, { tabs, activeId, onSelect },
    ),
  };
}
