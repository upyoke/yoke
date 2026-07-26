import { el } from "./universe_view_support.js";
import { relativeAge } from "./universe_time.js";

export const machineRelativeAge = relativeAge;

export function machinePanel(documentNode, title) {
  const root = el(documentNode, "section", "panel test-machine-panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, title));
  root.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  root.appendChild(body);
  return { root, body, header };
}

export function machineDefinitionList(documentNode, rows) {
  const list = el(documentNode, "dl", "test-machine-kv");
  for (const [label, value] of rows) {
    list.appendChild(el(documentNode, "dt", null, label));
    const cell = el(documentNode, "dd");
    if (value?.nodeType) cell.appendChild(value);
    else cell.textContent = String(value ?? "—");
    list.appendChild(cell);
  }
  return list;
}

export function machineVerificationCallout(documentNode, detail) {
  const verification = detail.verification || {};
  const verified = verification.status === "verified";
  const callout = el(
    documentNode,
    "div",
    `callout test-machine-callout ${verified ? "good" : "warn"}`,
  );
  callout.appendChild(el(
    documentNode, "span", "callout-icon", verified ? "✓" : "!",
  ));
  const copy = el(documentNode, "span");
  copy.appendChild(el(
    documentNode,
    "strong",
    null,
    verified
      ? `Verified ${machineRelativeAge(verification.checked_at)}.`
      : verification.status === "error"
        ? "Verification failed."
        : "Settings saved · verification required.",
  ));
  const explanation = verified
    ? " Connection, Terminal control, screenshot capture, PTY interaction and both named host baselines passed without returning secret values."
    : " The capability is not ready until the registered verifier re-checks the connection, control surfaces, and both host baselines.";
  copy.appendChild(
    documentNode.createTextNode
      ? documentNode.createTextNode(explanation)
      : el(documentNode, "span", null, explanation),
  );
  callout.appendChild(copy);
  return callout;
}
