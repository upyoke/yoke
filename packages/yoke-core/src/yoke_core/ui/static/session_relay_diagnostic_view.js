import { el } from "./universe_view_support.js";

export function appendRelayDiagnostic(
  documentNode, host, evidence, fallbackMachine = null,
) {
  if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) return false;
  const reference = String(evidence.native_diagnostic_ref || "").trim();
  const command = String(evidence.native_diagnostic_command || "").trim();
  const failureClass = String(evidence.native_error_class || "").trim();
  const failureStep = String(evidence.native_error_step || "").trim();
  const availability = String(evidence.diagnostic_availability || "").trim();
  if (!reference && !failureClass && !availability) return false;
  const machine = String(evidence.machine_id || fallbackMachine || "").trim();
  const relay = String(evidence.relay_id || "").trim();
  const location = [machine, relay].filter(Boolean).join(" / ");
  const callout = el(documentNode, "div", "session-relay-diagnostic");
  callout.appendChild(el(
    documentNode,
    "strong",
    "session-relay-diagnostic-title",
    reference ? `Native diagnostic ${reference}` : `Native failure: ${failureClass}`,
  ));
  if (failureStep) callout.appendChild(el(
    documentNode, "span", "session-relay-diagnostic-step", `Step: ${failureStep}`,
  ));
  if (availability) callout.appendChild(el(
    documentNode, "span", "session-relay-diagnostic-availability", `Detail: ${availability}`,
  ));
  if (location) callout.appendChild(el(
    documentNode, "span", "session-relay-diagnostic-location", `On ${location}`,
  ));
  if (reference && command) {
    const expires = String(evidence.diagnostic_expires_at || "").trim();
    if (expires) callout.appendChild(el(
      documentNode, "span", "session-relay-diagnostic-expiry", `Expires: ${expires}`,
    ));
    callout.appendChild(el(
      documentNode, "code", "session-relay-diagnostic-command", command,
    ));
  } else {
    callout.appendChild(el(
      documentNode, "span", "session-relay-diagnostic-unavailable", "Local detail unavailable.",
    ));
  }
  host.appendChild(callout);
  return true;
}
