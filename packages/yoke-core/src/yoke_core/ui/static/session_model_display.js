/**
 * Display a session's model without confusing the ask for what ran.
 *
 * `model` holds only what a provider attested it served, so an unattested
 * session has nothing there. Falling back to `requested_model` is useful —
 * it is often the only model fact a young session has — but it is shown
 * with an explicit label, because an unlabelled request in the model slot
 * reads as a report of what ran.
 */

export const REQUESTED_LABEL = " (requested)";

function compactTokenCount(value) {
  if (value === null || value === undefined) return "";
  const count = Number(value);
  if (!Number.isFinite(count) || count <= 0) return "";
  const scale = count >= 1_000_000
    ? [1_000_000, "m"]
    : count >= 1_000 ? [1_000, "k"] : null;
  if (!scale) return String(Math.round(count));
  const scaled = count / scale[0];
  const precision = scaled < 10 && !Number.isInteger(scaled) ? 1 : 0;
  return `${scaled.toFixed(precision).replace(/\.0$/, "")}${scale[1]}`;
}

export function servedSessionModelFacts(row) {
  const facts = [];
  const effort = String(row?.reasoning_effort ?? "").trim();
  if (effort) facts.push({ kind: "reasoning-effort", label: effort.toUpperCase() });
  const contextWindow = compactTokenCount(row?.context_window_tokens);
  if (contextWindow) facts.push({ kind: "context-window", label: contextWindow });
  return facts;
}

export function displaySessionModel(row, empty = "model not reported") {
  const served = String(row?.model || "").trim();
  if (served) return served;
  const requested = String(row?.requested_model || "").trim();
  if (requested) return `${requested}${REQUESTED_LABEL}`;
  return empty;
}
