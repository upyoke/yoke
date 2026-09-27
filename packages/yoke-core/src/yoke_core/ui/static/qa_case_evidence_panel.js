// The Evidence panel of a QA case page: the pictures a case captured, the
// output a command check recorded, the GitHub Actions run a CI-backed check
// rests on, and what the agent said about it.
//
// Evidence the shared chain could not resolve is unavailable, which is a
// different fact from a case that never ran and from one that captured
// nothing, so each says which it is rather than sharing one empty state.

import { evidenceStrip } from "./review_evidence_strip.js";
import {
  isCommandOutput,
  readRecordedOutput,
  recordedOutputNode,
} from "./qa_case_output_view.js";
import { runConclusionUrl } from "./qa_run_conclusion.js";
import { el } from "./universe_view_support.js";

const OUTPUT_LOADING = "loading recorded output…";
const OUTPUT_UNREADABLE = "The recorded output could not be read from here.";

// The exit code the command check recorded beside its output, when it did.
function recordedExitCode(artifact) {
  let meta = artifact.metadata;
  if (typeof meta === "string") {
    try { meta = JSON.parse(meta); } catch { meta = null; }
  }
  const code = meta?.exit_code;
  return Number.isInteger(code) ? code : null;
}

// Each recorded output fills in where it will sit once its bytes arrive, so
// the rest of the page does not wait on a read of every artifact.
function recordedOutputBlock(context, artifact, requirementId) {
  const documentNode = context.document;
  const block = el(documentNode, "div", "qa-case-output-block");
  const exitCode = recordedExitCode(artifact);
  const label = el(
    documentNode, "h3", "qa-case-output-label",
    exitCode == null ? "Recorded output" : `Recorded output · exit ${exitCode}`,
  );
  block.appendChild(label);
  block.appendChild(el(documentNode, "p", "empty", OUTPUT_LOADING));
  void readRecordedOutput(context, artifact, requirementId).then((text) => {
    if (context.isMounted && !context.isMounted()) return;
    block.replaceChildren(
      label,
      text === null
        ? el(documentNode, "p", "empty", OUTPUT_UNREADABLE)
        : recordedOutputNode(documentNode, text),
    );
  });
  return block;
}

function ciRunLink(documentNode, row) {
  const url = runConclusionUrl(row);
  if (!url) return null;
  const link = el(documentNode, "a", "qa-case-ci-link", "GitHub Actions run");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

export function caseEvidencePanel(context, { row, latest, requirementId }) {
  const documentNode = context.document;
  const section = el(documentNode, "section", "panel qa-case-evidence");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Evidence"));
  section.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  const artifacts = row?.artifacts || [];
  const outputs = artifacts.filter(isCommandOutput);
  const strip = evidenceStrip(
    context,
    artifacts.filter((artifact) => !isCommandOutput(artifact)),
    { requirementId: Number(requirementId) },
  );
  if (strip) body.appendChild(strip);
  for (const artifact of outputs) {
    body.appendChild(recordedOutputBlock(context, artifact, requirementId));
  }
  const ci = ciRunLink(documentNode, row);
  if (ci) body.appendChild(ci);
  for (const [label, value] of [
    ["What the agent said", latest?.verdict_reason || row?.verdict_reason],
    ["Capture degraded", latest?.capture_degraded_reason],
    ["Blocked on precondition", row?.precondition_reason],
  ]) {
    if (!value) continue;
    const line = el(documentNode, "p", "qa-case-reason");
    line.appendChild(el(documentNode, "strong", null, `${label}: `));
    line.appendChild(el(documentNode, "span", null, String(value)));
    body.appendChild(line);
  }
  if (latest && !row) {
    body.appendChild(el(
      documentNode,
      "p",
      "empty",
      "This execution's evidence could not be resolved from here.",
    ));
  } else if (!body.children.length) {
    body.appendChild(el(
      documentNode,
      "p",
      "empty",
      latest ? "No evidence was captured." : "This case has never run.",
    ));
  }
  section.appendChild(body);
  return section;
}
