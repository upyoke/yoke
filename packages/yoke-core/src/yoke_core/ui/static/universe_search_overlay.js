// Responsive frame for the shared search field. The same input and result
// list move into a modal overlay below the drawer breakpoint, so search keeps
// one query state and one keyboard model at every width.

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function magnifier(documentNode) {
  if (typeof documentNode.createElementNS !== "function") {
    return el(documentNode, "span", "header-search-icon", "⌕");
  }
  const svg = documentNode.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "header-search-icon");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("aria-hidden", "true");
  const circle = documentNode.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", "8.5");
  circle.setAttribute("cy", "8.5");
  circle.setAttribute("r", "5.5");
  circle.setAttribute("fill", "none");
  circle.setAttribute("stroke", "currentColor");
  circle.setAttribute("stroke-width", "1.6");
  const line = documentNode.createElementNS("http://www.w3.org/2000/svg", "path");
  line.setAttribute("d", "m12.7 12.7 4 4");
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "currentColor");
  line.setAttribute("stroke-width", "1.6");
  line.setAttribute("stroke-linecap", "round");
  svg.appendChild(circle);
  svg.appendChild(line);
  return svg;
}

function compactViewport(windowNode) {
  if (typeof windowNode.matchMedia === "function") {
    return windowNode.matchMedia("(max-width: 980px)").matches;
  }
  return Number(windowNode.innerWidth || 1200) <= 980;
}

export function createSearchFrame(documentNode) {
  const windowNode = documentNode.defaultView;
  const root = el(documentNode, "div", "shell-search");
  const inlineHost = el(documentNode, "div", "shell-search-inline");
  const trigger = el(documentNode, "button", "header-search-button");
  trigger.type = "button";
  trigger.setAttribute("aria-label", "Open search");
  trigger.setAttribute("aria-expanded", "false");
  trigger.appendChild(magnifier(documentNode));

  const overlay = el(documentNode, "div", "header-search-overlay");
  overlay.hidden = true;
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Search items and sessions");
  const backdrop = el(documentNode, "button", "header-search-backdrop");
  backdrop.type = "button";
  backdrop.setAttribute("aria-label", "Close search");
  const panel = el(documentNode, "div", "header-search-panel");
  const fieldHost = el(documentNode, "div", "header-search-overlay-field");
  const closeButton = el(
    documentNode, "button", "header-search-close", "Esc",
  );
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close search");
  fieldHost.appendChild(closeButton);
  panel.appendChild(fieldHost);
  overlay.appendChild(backdrop);
  overlay.appendChild(panel);
  root.appendChild(inlineHost);
  root.appendChild(trigger);
  root.appendChild(overlay);

  let searchHost = null;
  let input = null;
  const closeOverlay = () => {
    if (searchHost && searchHost.parentNode !== inlineHost) {
      inlineHost.appendChild(searchHost);
    }
    overlay.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  };
  const openOverlay = () => {
    if (!searchHost) return;
    fieldHost.replaceChildren(searchHost, closeButton);
    overlay.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    input?.focus?.();
  };
  trigger.addEventListener("click", openOverlay);
  backdrop.addEventListener("click", closeOverlay);
  closeButton.addEventListener("click", closeOverlay);

  return {
    closeOverlay,
    focus() {
      if (compactViewport(windowNode)) openOverlay();
      else input?.focus?.();
    },
    mount(host, searchInput) {
      searchHost = host;
      input = searchInput;
      inlineHost.appendChild(host);
    },
    openOverlay,
    root,
  };
}
