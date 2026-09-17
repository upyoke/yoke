// The search dialog: one centred panel over a dimmed app, at every width.
//
// The header field is the entry point, not the feature. It is a button shaped
// like a field — clicking it, or pressing the shortcut it already advertises,
// opens the same panel the narrow icon button opens. Search therefore has one
// query state, one result list, and one keyboard model everywhere, instead of
// an inline dropdown at desktop and a different surface on a phone.

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// A drawn glyph rather than a font character: the ⌕ codepoint renders at
// wildly different sizes across fonts, so an SVG is the only way the icon is
// the same size in the field and in the button.
function magnifier(documentNode, className) {
  if (typeof documentNode.createElementNS !== "function") {
    return el(documentNode, "span", className, "⌕");
  }
  const ns = "http://www.w3.org/2000/svg";
  const svg = documentNode.createElementNS(ns, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("aria-hidden", "true");
  const circle = documentNode.createElementNS(ns, "circle");
  for (const [name, value] of [
    ["cx", "8.5"], ["cy", "8.5"], ["r", "5.5"], ["fill", "none"],
    ["stroke", "currentColor"], ["stroke-width", "1.6"],
  ]) circle.setAttribute(name, value);
  const line = documentNode.createElementNS(ns, "path");
  for (const [name, value] of [
    ["d", "m12.7 12.7 4 4"], ["fill", "none"], ["stroke", "currentColor"],
    ["stroke-width", "1.6"], ["stroke-linecap", "round"],
  ]) line.setAttribute(name, value);
  svg.appendChild(circle);
  svg.appendChild(line);
  return svg;
}

function triggers(documentNode, controlId) {
  const field = el(documentNode, "button", "header-search");
  field.type = "button";
  field.id = `universe-search-trigger-${controlId}`;
  field.setAttribute("aria-haspopup", "dialog");
  field.setAttribute("aria-expanded", "false");
  field.appendChild(magnifier(documentNode, "header-search-icon"));
  field.appendChild(el(
    documentNode, "span", "header-search-placeholder", "Search this universe",
  ));
  field.appendChild(el(documentNode, "kbd", "header-search-key", "⌘K"));
  const button = el(documentNode, "button", "header-search-button");
  button.type = "button";
  button.setAttribute("aria-label", "Search this universe");
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-expanded", "false");
  button.appendChild(magnifier(documentNode, "header-search-icon"));
  return { button, field };
}

export function createSearchDialog(documentNode, controlId, onOpened) {
  const root = el(documentNode, "div", "shell-search");
  const { button, field } = triggers(documentNode, controlId);

  const overlay = el(documentNode, "div", "header-search-overlay");
  overlay.hidden = true;
  const backdrop = el(documentNode, "button", "header-search-backdrop");
  backdrop.type = "button";
  backdrop.setAttribute("aria-label", "Close search");
  backdrop.tabIndex = -1;

  const panel = el(documentNode, "div", "header-search-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-labelledby", `universe-search-title-${controlId}`);
  const title = el(
    documentNode, "h2", "shell-visually-hidden", "Search this universe",
  );
  title.id = `universe-search-title-${controlId}`;

  const fieldRow = el(documentNode, "div", "header-search-field");
  fieldRow.appendChild(magnifier(documentNode, "header-search-icon"));
  const input = el(documentNode, "input", "header-search-input");
  input.id = `universe-search-input-${controlId}`;
  input.type = "search";
  input.placeholder = "Search items, sessions, docs, plans, events, packs…";
  input.setAttribute("aria-label", "Search this universe");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `universe-search-results-${controlId}`);
  input.setAttribute("autocomplete", "off");
  const closeButton = el(documentNode, "button", "header-search-close", "Esc");
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close search");
  fieldRow.appendChild(input);
  fieldRow.appendChild(closeButton);

  const body = el(documentNode, "div", "header-search-body");
  body.id = `universe-search-results-${controlId}`;
  panel.appendChild(title);
  panel.appendChild(fieldRow);
  panel.appendChild(body);
  overlay.appendChild(backdrop);
  overlay.appendChild(panel);
  root.appendChild(field);
  root.appendChild(button);
  root.appendChild(overlay);

  let restoreFocusTo = null;
  const isOpen = () => !overlay.hidden;
  const setExpanded = (value) => {
    for (const node of [field, button]) {
      node.setAttribute("aria-expanded", value ? "true" : "false");
    }
  };
  const close = () => {
    if (!isOpen()) return;
    overlay.hidden = true;
    setExpanded(false);
    // Dismissal returns the operator where they were: the control they
    // opened search from, not the top of the document.
    restoreFocusTo?.focus?.();
    restoreFocusTo = null;
  };
  const open = (opener) => {
    if (isOpen()) {
      input.focus?.();
      return;
    }
    restoreFocusTo = opener || null;
    overlay.hidden = false;
    setExpanded(true);
    input.focus?.();
    onOpened?.();
  };
  field.addEventListener("click", () => open(field));
  button.addEventListener("click", () => open(button));
  backdrop.addEventListener("click", close);
  closeButton.addEventListener("click", close);
  // A modal dialog owns the focus while it is open: tabbing past its last
  // control must not land on the page it is covering.
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = [...panel.querySelectorAll("input,button,a[href]")]
      .filter((node) => !node.disabled && node.tabIndex !== -1);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = documentNode.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  });

  return {
    body,
    close,
    input,
    isOpen,
    open,
    root,
  };
}
