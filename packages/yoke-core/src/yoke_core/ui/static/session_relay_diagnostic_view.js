import { el } from "./universe_view_support.js";

export function appendRelayDiagnostic(
  documentNode, host, evidence, fallbackMachine = null,
) {
  if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) return false;
  const reference = String(evidence.native_diagnostic_ref || "").trim();
  const command = String(evidence.native_diagnostic_command || "").trim();
  if (!reference || !command) return false;
  const machine = String(evidence.machine_id || fallbackMachine || "").trim();
  const relay = String(evidence.relay_id || "").trim();
  const location = [machine, relay].filter(Boolean).join(" / ");
  const callout = el(documentNode, "div", "session-relay-diagnostic");
  callout.appendChild(el(
    documentNode,
    "strong",
    "session-relay-diagnostic-title",
    `Native diagnostic ${reference}`,
  ));
  if (location) callout.appendChild(el(
    documentNode, "span", "session-relay-diagnostic-location", `On ${location}`,
  ));
  callout.appendChild(el(
    documentNode,
    "code",
    "session-relay-diagnostic-command",
    command,
  ));
  host.appendChild(callout);
  return true;
}
