import { formatInstant } from "./timestamps.js";
import { textPanel } from "./item_view_shell.js";

// Shepherd verdicts come from items.detail.get's shepherd_verdicts, newest
// first. Each verdict is a heading for its transition and date, the verdict
// with its worker and attempt, then the reviewer's caveats as written.
function verdictMarkdown(verdict) {
  const date = formatInstant(verdict.created_at).slice(0, 10);
  const lines = [
    `### ${verdict.transition} · ${date}`,
    "",
    `**${verdict.verdict}** · ${verdict.worker} · attempt ${verdict.attempt}`,
  ];
  const caveats = String(verdict.caveats || "").trim();
  if (caveats) lines.push("", caveats);
  return lines.join("\n");
}

export function shepherdVerdictsPanel(documentNode, item) {
  const verdicts = item.shepherd_verdicts || [];
  return textPanel(
    documentNode,
    "Shepherd verdicts",
    verdicts.map(verdictMarkdown).join("\n\n"),
    "No shepherd verdict recorded.",
  );
}

// Workflows that do not always run shepherd show the panel only when the
// item has verdicts.
export function filledVerdictPanels(documentNode, item) {
  return (item.shepherd_verdicts || []).length
    ? [shepherdVerdictsPanel(documentNode, item)]
    : [];
}
