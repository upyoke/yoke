// The Universe settings screen. Its Portability panel is where a universe
// moves between homes. The mount contract names the deployment mode instead
// of asking the view to infer it from whichever actions happen to be present.
// A hosted shell can own the whole panel as a live section; local and
// self-host views keep honest, mode-specific command guidance because this
// read-only workbench has no write path of its own.

import { el } from "./universe_view_support.js";

function invokeAction(action, option) {
  // Invoke during the originating DOM event so host actions that require
  // transient user activation (for example a file picker) retain it. Surface
  // both synchronous throws and rejected async handlers without coupling the
  // workbench to host-specific error concepts.
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

// One real button per invocable: an action without options is one button
// wearing the action's label; an action with options is one button per
// option, each wearing that option's label and invoking with it.
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

// A command the operator runs from a terminal on the universe's own machine:
// one plain sentence, then the command as copyable code — never a button,
// because nothing on this server could carry the click out.
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

export function renderUniverseSettingsView(context, main) {
  const documentNode = context.document;
  const capabilities = context.capabilities || {};
  if (hostOwnsPortabilitySection(capabilities)) {
    // The app will append the supplied host section immediately after this
    // renderer returns. Leaving the view empty makes that one section the
    // complete Portability surface instead of stacking two partial panels.
    main.replaceChildren();
    return;
  }
  // A hand-built panel rather than the shared section(): no function read
  // backs this screen, so there is no response envelope for the raw-JSON
  // toggle to show, and a toggle over nothing would be one more control
  // that lies.
  const panel = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Portability"));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  panel.appendChild(body);
  main.replaceChildren(panel);

  const actions = (Array.isArray(capabilities.actions)
    ? capabilities.actions : []
  ).filter((action) => action && typeof action.onInvoke === "function");
  if (actions.length > 0) appendHostActions(documentNode, body, actions);
  else if (portabilityMode(capabilities) === "self-host") {
    appendSelfHostCommands(documentNode, body);
  } else appendLocalCommands(documentNode, body);
}
