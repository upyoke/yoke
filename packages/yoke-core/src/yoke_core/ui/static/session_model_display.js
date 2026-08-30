/** Display the stored session model name verbatim. */

export function displaySessionModel(row, empty = "model not reported") {
  const model = String(row?.model || "").trim();
  if (!model) return empty;
  return model;
}
