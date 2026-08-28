import { el } from "./universe_view_support.js";

export function presentationLabel(row) {
  if (row.presentation_state === "not-attached") return "local only";
  if (
    row.presentation_state !== "attached"
    || row.presentation_surface !== "remote-control"
  ) return "";
  const mode = row.presentation_mode === "bidirectional"
    ? "bidirectional"
    : row.presentation_mode === "outbound-only" ? "outbound only" : "mode unknown";
  return `Remote Control · ${mode}`;
}

export function appendSessionPresentation(documentNode, body, row) {
  const label = presentationLabel(row);
  if (!label) return;
  const line = el(
    documentNode,
    "div",
    "session-presentation",
    `Presentation: ${label}`,
  );
  line.title = "Observed attachment only; initiating authority and frontend are unknown.";
  body.appendChild(line);
}

export function remotePresentationCount(rows) {
  return rows.filter((row) => presentationLabel(row).startsWith("Remote Control")).length;
}
