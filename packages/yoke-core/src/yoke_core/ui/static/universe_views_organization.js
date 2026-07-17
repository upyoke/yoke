// The Organization screen identifies the universe's organization and explains
// how the universe moves between homes. Identity comes from the engine. The
// mount contract names the portability mode and lets a hosted shell own the
// complete portability surface; local and self-host views keep honest command
// guidance because this read-only workbench has no write path of its own.

import { el, loadSection, section } from "./universe_view_support.js";

function invokeAction(action, option) {
  let result;
  try {
    result = action.onInvoke(option);
  } catch (error) {
    globalThis.console.error("universe capability action failed", error);
    return;
  }
  Promise.resolve(result).catch((error) => {
    globalThis.console.error("universe capability action failed", error);
  });
}

function appendHostActions(documentNode, body, actions) {
  const row = el(documentNode, "div", "capability-actions");
  for (const action of actions) {
    const options = Array.isArray(action.options) ? action.options : [];
    const buttons = options.length === 0
      ? [[String(action.label || ""), undefined]]
      : options.map((option) => [
        String(option.label || option.id || ""), option,
      ]);
    for (const [label, option] of buttons) {
      const button = el(documentNode, "button", "capability-action", label);
      button.type = "button";
      button.addEventListener("click", () => invokeAction(action, option));
      row.appendChild(button);
    }
  }
  body.appendChild(row);
}

function commandLine(documentNode, description, command) {
  const line = el(documentNode, "p", "fact-line", `${description} `);
  line.appendChild(el(documentNode, "code", null, command));
  return line;
}

function appendLocalCommands(documentNode, body) {
  body.appendChild(commandLine(
    documentNode,
    "Export this universe to one portable archive:",
    "yoke universe export",
  ));
  body.appendChild(commandLine(
    documentNode,
    "Check an archive's format and freeze receipt:",
    "yoke universe validate <archive>",
  ));
  body.appendChild(commandLine(
    documentNode,
    "Replace this local universe from a portable archive:",
    "yoke universe import <archive>",
  ));
}

function appendSelfHostCommands(documentNode, body) {
  body.appendChild(commandLine(
    documentNode,
    "Download one portable archive from this HTTPS server:",
    "yoke universe export --out <directory>",
  ));
  body.appendChild(commandLine(
    documentNode,
    "Check the archive before replacing a server:",
    "yoke universe validate <archive>",
  ));
  body.appendChild(commandLine(
    documentNode,
    "Replace a stopped self-host bundle from that archive:",
    "yoke self-host import <archive> --dir <bundle>",
  ));
}

function portabilityMode(capabilities) {
  const portability = capabilities?.data?.portability;
  if (!portability || typeof portability !== "object") return "local";
  return ["local", "self-host", "hosted"].includes(portability.mode)
    ? portability.mode : "local";
}

function hostOwnsPortabilitySection(capabilities) {
  const portability = capabilities?.data?.portability;
  return portabilityMode(capabilities) === "hosted"
    && portability && typeof portability === "object"
    && portability.sectionOwned === true;
}

function renderIdentityPanel(context, main) {
  const documentNode = context.document;
  const panel = section(documentNode, "Identity");
  main.appendChild(panel);
  loadSection(
    context, panel, "organizations.get", {},
    (body, callResult) => {
      const org = callResult.envelope.result || {};
      const table = el(documentNode, "table", "items kv");
      for (const [label, value] of [
        ["name", org.name],
        ["url name", org.slug],
        ["created", org.created_at],
      ]) {
        const row = el(documentNode, "tr");
        row.appendChild(el(documentNode, "th", null, label));
        row.appendChild(el(documentNode, "td", null, String(value ?? "")));
        table.appendChild(row);
      }
      body.appendChild(table);
    },
  );
}

function renderPortabilityPanel(context, main) {
  const documentNode = context.document;
  const capabilities = context.capabilities || {};
  if (hostOwnsPortabilitySection(capabilities)) return;

  const panel = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Portability"));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(el(
    documentNode, "p", "fact-line",
    "A universe is portable: it exports to one archive, and that archive " +
      "imports into another home.",
  ));
  panel.appendChild(body);
  main.appendChild(panel);

  const actions = (Array.isArray(capabilities.actions)
    ? capabilities.actions : []
  ).filter((action) => action && typeof action.onInvoke === "function");
  if (actions.length > 0) appendHostActions(documentNode, body, actions);
  else if (portabilityMode(capabilities) === "self-host") {
    appendSelfHostCommands(documentNode, body);
  } else appendLocalCommands(documentNode, body);
}

export function renderOrganizationView(context, main) {
  main.replaceChildren();
  renderIdentityPanel(context, main);
  renderPortabilityPanel(context, main);
}
