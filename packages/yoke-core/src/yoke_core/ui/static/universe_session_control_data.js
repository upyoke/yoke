import { callFunction, el } from "./universe_view_support.js";

const PLAIN_FAILURES = {
  actor_required: "Sign in before using session controls.",
  body_empty: "Add a message before sending.",
  body_too_large: "That message is too large to send.",
  broadcast_confirmation_required: "The broadcast recipients changed after preview.",
  invalid_response: "Session control returned an unreadable response.",
  network_unavailable: "Session control is temporarily unavailable.",
  not_found: "That session-control record is no longer available.",
  permission_denied: "You do not have permission for that session-control action.",
  project_not_found: "That project is no longer available.",
  recipient_session_unregistered: "The recipient is not a registered top-level session.",
  reconcile_required: "This launch has an uncertain native outcome.",
  reconciliation_conflict: "The recorded and observed launch outcomes disagree.",
  sender_session_unregistered: "This sender is not a registered top-level session.",
  session_required: "A registered recipient session is required.",
  subagent_message_forbidden: "In-process subagents do not use Fleet messaging directly.",
  target_not_found: "No recipient matched the selected target.",
  unsupported_route: "One or more selected sessions cannot receive Fleet messages.",
  zero_recipients: "No sessions matched those recipients.",
};

const RECOVERY_BY_CODE = {
  broadcast_confirmation_required: "Preview the recipients again, then send.",
  invalid_response: "Refresh the page and try again.",
  network_unavailable: "Check the connection, then try again.",
  not_found: "Refresh the page before choosing another action.",
  project_not_found: "Refresh the project list and choose an available project.",
  recipient_session_unregistered: "Refresh the roster and choose a registered session.",
  reconcile_required: "Reconcile whether a native session exists before retrying.",
  reconciliation_conflict: "Review the native session identity before continuing.",
  sender_session_unregistered: "Refresh session registration before sending.",
  session_required: "Refresh the roster and try again from a registered session.",
  subagent_message_forbidden: "Send through the parent session's native agent channel.",
  unsupported_route: "Choose a session marked Messageable in the roster.",
  zero_recipients: "Check the IDs and filters, then preview again.",
};

const TECHNICAL_DETAIL = /HTTP undefined|\b(?:SQL(?:STATE)?|SQLite|Postgres(?:QL)?|database|relation|column|table|constraint|traceback|operationalerror|programmingerror|psycopg)\b|\b(?:SELECT|INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b/i;

function safeSentence(value) {
  const text = typeof value === "string"
    ? value.replace(/\s+/g, " ").trim()
    : "";
  return text && text.length <= 280 && !TECHNICAL_DETAIL.test(text) ? text : null;
}

function punctuated(value) {
  return /[.!?]$/.test(value) ? value : `${value}.`;
}

export class SessionControlFailure extends Error {
  constructor({ code, detail, recovery, status } = {}) {
    super("Session control request failed.");
    this.name = "SessionControlFailure";
    this.code = String(code || "invalid_response").toLowerCase();
    this.detail = safeSentence(detail);
    this.recovery = safeSentence(recovery);
    this.status = Number.isInteger(status) ? status : null;
  }
}

function responseFailure(response) {
  const envelope = response?.envelope || {};
  const error = envelope.error || {};
  return new SessionControlFailure({
    code: error.code || (error.message ? "request_failed" : "invalid_response"),
    detail: error.message,
    recovery: error.recovery_hint || error.recovery || error.hint,
    status: response?.status,
  });
}

export async function sessionControlCall(context, functionId, payload = {}) {
  let response;
  try {
    response = await callFunction(context.client, functionId, payload);
  } catch (_error) {
    throw new SessionControlFailure({ code: "network_unavailable" });
  }
  const envelope = response?.envelope || {};
  if (response?.status !== 200 || !envelope.success) {
    throw responseFailure(response);
  }
  return envelope.result || {};
}

export function presentSessionControlFailure(
  error,
  fallback = "Session control request failed.",
) {
  const failure = error instanceof SessionControlFailure
    ? error
    : error?.envelope
      ? responseFailure(error)
      : new SessionControlFailure({ code: "network_unavailable" });
  const message = PLAIN_FAILURES[failure.code]
    || failure.detail
    || safeSentence(fallback)
    || "Session control request failed.";
  const recovery = failure.recovery || RECOVERY_BY_CODE[failure.code];
  return recovery
    ? `${punctuated(message)} ${punctuated(recovery)}`
    : punctuated(message);
}

export function renderSessionControlFailure(host, error, fallback) {
  host.replaceChildren(el(
    host.ownerDocument,
    "p",
    "error",
    presentSessionControlFailure(error, fallback),
  ));
}

export function scopedProjectRefs(context, scope) {
  const selected = scope === "all"
    ? null
    : new Set(scope.map((value) => String(value)));
  return context.projects().filter((project) => (
    selected === null || selected.has(String(project.id))
  )).map((project) => String(project.id || project.slug));
}

export function sessionControlIdempotencyKey(prefix) {
  const generated = globalThis.crypto?.randomUUID?.();
  return generated
    ? `${prefix}:${generated}`
    : `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
}

export function labelledControl(documentNode, labelText, control) {
  const label = el(documentNode, "label", "session-control-field");
  label.appendChild(el(documentNode, "span", null, labelText));
  label.appendChild(control);
  return label;
}

export function formatSessionControlTime(value) {
  const text = String(value || "").trim();
  if (!text) return "—";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  return `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function statusRegion(documentNode, className = "session-control-status") {
  const status = el(documentNode, "p", className);
  status.hidden = true;
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  return status;
}

export function splitValues(value) {
  return String(value || "").split(/[\s,]+/).map((part) => part.trim())
    .filter(Boolean);
}
