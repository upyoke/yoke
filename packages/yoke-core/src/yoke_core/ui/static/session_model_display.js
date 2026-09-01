/**
 * Display a session's model without confusing the ask for what ran.
 *
 * `model` holds only what a provider attested it served, so an unattested
 * session has nothing there. Falling back to `requested_model` is useful —
 * it is often the only model fact a young session has — but it is shown
 * with an explicit label, because an unlabelled request in the model slot
 * reads as a report of what ran. The same rule paints effort and context
 * tags: served wins, else the labelled ask, else nothing.
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

function compactEffort(value) {
  const effort = String(value ?? "").trim();
  return effort ? effort.toUpperCase() : "";
}

function compactModel(value) {
  return String(value ?? "").trim();
}

function servedOrRequested(kind, servedValue, requestedValue, format) {
  const served = format(servedValue);
  if (served) return { kind, label: served, requested: false };
  const requested = format(requestedValue);
  if (requested) {
    return { kind, label: `${requested}${REQUESTED_LABEL}`, requested: true };
  }
  return null;
}

export function sessionModelIsRequested(row) {
  return Boolean(servedOrRequested(
    "model", row?.model, row?.requested_model, compactModel,
  )?.requested);
}

export function sessionModelFactTags(row) {
  return [
    servedOrRequested(
      "reasoning-effort",
      row?.reasoning_effort,
      row?.requested_reasoning_effort,
      compactEffort,
    ),
    servedOrRequested(
      "context-window",
      row?.context_window_tokens,
      row?.requested_context_window_tokens,
      compactTokenCount,
    ),
  ].filter(Boolean);
}

export function displaySessionModel(row, empty = "model not reported") {
  const fact = servedOrRequested(
    "model", row?.model, row?.requested_model, compactModel,
  );
  return fact ? fact.label : empty;
}
