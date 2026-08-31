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

export function displaySessionModel(row, empty = "model not reported") {
  const served = String(row?.model || "").trim();
  if (served) return served;
  const requested = String(row?.requested_model || "").trim();
  if (requested) return `${requested}${REQUESTED_LABEL}`;
  return empty;
}
