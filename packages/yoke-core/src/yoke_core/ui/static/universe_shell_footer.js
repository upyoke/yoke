// Footer strip: environment label, docs/keyboard links, and the activatable
// version control that reveals the host's runtime-identity packet.

const DEFAULT_DOCS_URL = "https://github.com/upyoke/yoke/tree/main/docs";
const SOURCE_VERSION_LABEL = "source";

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function environmentLabel(options) {
  if (options.environmentLabel) return String(options.environmentLabel);
  const packet = options.runtimeIdentity;
  if (packet?.environmentLabel) return String(packet.environmentLabel);
  const mode = options.capabilities?.data?.portability?.mode;
  if (mode === "hosted") return "hosted universe";
  if (mode === "selfhost") return "self-hosted universe";
  return "local universe";
}

function versionLabel(options) {
  if (options.versionLabel) return String(options.versionLabel);
  const packet = options.runtimeIdentity;
  if (packet?.version) return String(packet.version);
  return SOURCE_VERSION_LABEL;
}

function identityDetailRows(options) {
  const packet = options.runtimeIdentity;
  if (!packet) {
    return [["Version", versionLabel(options)]];
  }
  const rows = [
    ["Version", String(packet.version || SOURCE_VERSION_LABEL)],
    ["Install", String(packet.installKind || "")],
  ];
  if (packet.build) rows.push(["Build", String(packet.build)]);
  rows.push(
    ["Environment", String(packet.environmentLabel || "")],
    ["Mode", String(packet.portabilityMode || "")],
  );
  return rows;
}

function createTogglePanel(documentNode, {
  className, ariaLabel, rows, labelKeyClass, valueClass,
}) {
  const panel = el(documentNode, "div", className);
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", ariaLabel);
  for (const [label, value] of rows) {
    const row = el(documentNode, "div", `${className}-row`);
    row.appendChild(el(documentNode, labelKeyClass.tag, labelKeyClass.name, label));
    row.appendChild(el(documentNode, "span", valueClass, value));
    panel.appendChild(row);
  }
  return panel;
}

export function createFooter(documentNode, options) {
  const footer = el(documentNode, "footer", "app-footer");
  footer.appendChild(el(documentNode, "span", "app-footer-mark", "Yoke"));
  footer.appendChild(el(
    documentNode, "span", "app-footer-environment", environmentLabel(options),
  ));
  const links = el(documentNode, "span", "app-footer-links");
  const docs = el(documentNode, "a", "app-footer-link", "Docs");
  docs.href = String(options.docsUrl || DEFAULT_DOCS_URL);
  docs.target = "_blank";
  docs.rel = "noopener noreferrer";
  links.appendChild(docs);
  const keyboard = el(
    documentNode, "button", "app-footer-link keyboard-help-toggle", "Keyboard",
  );
  keyboard.type = "button";
  keyboard.setAttribute("aria-expanded", "false");
  links.appendChild(keyboard);
  const version = el(
    documentNode, "button", "app-footer-link app-footer-version",
    versionLabel(options),
  );
  version.type = "button";
  version.setAttribute("aria-expanded", "false");
  version.setAttribute("aria-label", "Runtime identity");
  links.appendChild(version);
  footer.appendChild(links);
  const keyboardPanel = createTogglePanel(documentNode, {
    className: "keyboard-help",
    ariaLabel: "Keyboard shortcuts",
    rows: [
      ["⌘K / Ctrl K", "Search items and sessions"],
      ["↑ / ↓", "Move through search results"],
      ["Enter", "Open the selected result"],
      ["Esc", "Close search or keyboard help"],
    ],
    labelKeyClass: { tag: "kbd", name: null },
    valueClass: null,
  });
  const identityPanel = createTogglePanel(documentNode, {
    className: "runtime-identity-help",
    ariaLabel: "Runtime identity",
    rows: identityDetailRows(options),
    labelKeyClass: { tag: "span", name: "runtime-identity-help-label" },
    valueClass: "runtime-identity-help-value",
  });
  footer.appendChild(keyboardPanel);
  footer.appendChild(identityPanel);
  const closePanels = () => {
    keyboardPanel.hidden = true;
    identityPanel.hidden = true;
    keyboard.setAttribute("aria-expanded", "false");
    version.setAttribute("aria-expanded", "false");
  };
  keyboard.addEventListener("click", () => {
    const open = keyboardPanel.hidden;
    closePanels();
    if (open) {
      keyboardPanel.hidden = false;
      keyboard.setAttribute("aria-expanded", "true");
    }
  });
  version.addEventListener("click", () => {
    const open = identityPanel.hidden;
    closePanels();
    if (open) {
      identityPanel.hidden = false;
      version.setAttribute("aria-expanded", "true");
    }
  });
  return { footer, keyboardPanel, identityPanel, closePanels };
}
