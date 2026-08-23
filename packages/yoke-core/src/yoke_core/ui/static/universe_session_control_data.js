import { callFunction, el } from "./universe_view_support.js";

export async function sessionControlCall(context, functionId, payload = {}) {
  const response = await callFunction(context.client, functionId, payload);
  const envelope = response.envelope || {};
  if (response.status !== 200 || !envelope.success) {
    throw new Error((envelope.error || {}).message || `${functionId} failed`);
  }
  return envelope.result || {};
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
