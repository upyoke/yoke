/** Display the stored session model without repeating the harness family. */

export function displaySessionModel(row, empty = "model not reported") {
  const model = String(row?.model || "").trim();
  if (!model) return empty;
  const harness = String(row.executor_surface || row.executor || "").toLowerCase();
  if (
    (harness === "cursor" || harness.startsWith("cursor-"))
    && model.toLowerCase().startsWith("cursor-")
  ) {
    return model.slice("cursor-".length);
  }
  return model;
}
