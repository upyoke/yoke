// Minimal element helper, so the prototype builds nodes the same shape the
// product's views do without importing any shipped module.

export function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

export function panel(documentNode, title, options = {}) {
  const host = el(documentNode, "section", "panel workflow-panel");
  const header = el(documentNode, "div", "panel-header workflow-panel-header");
  const heading = el(documentNode, "h2", null, title);
  if (options.count !== undefined) {
    heading.appendChild(el(documentNode, "span", "panel-count",
      `· ${options.count}`));
  }
  header.appendChild(heading);
  if (options.meta) {
    const meta = el(documentNode, "div", "workflow-panel-meta");
    meta.appendChild(el(documentNode, "span", "workflow-version", options.meta));
    header.appendChild(meta);
  }
  host.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  host.appendChild(body);
  return { panel: host, body };
}

export function button(documentNode, text, className = "workflow-button") {
  const node = el(documentNode, "button", className, text);
  node.type = "button";
  return node;
}

export function checkbox(documentNode, checked, label, className, toggle) {
  const row = el(documentNode, "label",
    ["workflow-checkbox", className].filter(Boolean).join(" "));
  const input = documentNode.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", toggle);
  row.appendChild(input);
  row.appendChild(el(documentNode, "span", null, label));
  return { row, input };
}

export function formatDay(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric",
  }).format(date);
}
