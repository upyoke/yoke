import { el } from "./universe_view_support.js";

export function failureOutputNode(documentNode, result) {
  const output = result.output_tail;
  if (result.outcome !== "failed" || typeof output !== "string" || !output) {
    return null;
  }
  const details = el(documentNode, "details", "qa-case-output");
  details.appendChild(el(documentNode, "summary", null, "failure output"));
  details.appendChild(el(documentNode, "pre", "qa-case-output-text", output));
  return details;
}
