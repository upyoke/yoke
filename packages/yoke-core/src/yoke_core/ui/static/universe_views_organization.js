// The Organization screen: which organization this universe belongs to, and
// how the universe moves between homes.
//
// Identity comes from `organizations.get` — the engine's org card is a slug, a
// name, and a creation stamp and nothing more, so those three are what the
// panel shows. Portability is where a universe moves: hosted, the host passes
// real move actions through the mount contract's capabilities bag, and each
// renders as a button that acts on click. Locally, the UI server is a closed
// read-only allowlist with no write path, so no control here could act — the
// honest affordance is each CLI command as text to copy.

import { el, loadSection, section } from "./universe_view_support.js";

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
  body.appendChild(el(
    documentNode, "p", "empty",
    "Importing into a local universe is not available yet; hosted import " +
      "lives in the host dashboard.",
  ));
}

// The engine's org card, verbatim. A universe holds exactly one organization,
// so this reads without a scope and the screen carries no picker.
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

// A hand-built panel rather than the shared section(): no function read backs
// portability, so there is no response envelope for a raw-JSON toggle to show,
// and a toggle over nothing would be one more control that lies.
function renderPortabilityPanel(context, main) {
  const documentNode = context.document;
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

  const capabilities = context.capabilities || {};
  const actions = (Array.isArray(capabilities.actions)
    ? capabilities.actions : []
  ).filter((action) => action && typeof action.onInvoke === "function");
  if (actions.length > 0) appendHostActions(documentNode, body, actions);
  else appendLocalCommands(documentNode, body);
}

export function renderOrganizationView(context, main) {
  main.replaceChildren();
  renderIdentityPanel(context, main);
  renderPortabilityPanel(context, main);
}
