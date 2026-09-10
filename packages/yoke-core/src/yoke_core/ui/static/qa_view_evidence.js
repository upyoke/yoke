import { el } from "./universe_view_support.js";
import { artifactEvidenceCard } from "./qa_evidence_artifact_view.js";
import { qaPanel } from "./qa_view_primitives.js";

export function renderEvidence(context, plan) {
  const documentNode = context.document;
  const caseEvidence = plan.cases.map((row) => ({
    case_key: row.case_key,
    artifacts: (row.last_result.evidence || []).map((artifact) => ({
      ...artifact,
      case_key: row.case_key,
      requirement_id: row.last_result.requirement_id,
    })),
  })).filter((row) => row.artifacts.length);
  const artifacts = caseEvidence.flatMap((row) => row.artifacts);
  const title = caseEvidence.length === 1
    ? `Evidence · ${caseEvidence[0].case_key}`
    : caseEvidence.length > 1 ? "Evidence by case" : "Evidence";
  const result = qaPanel(
    documentNode,
    title,
    caseEvidence.length === 1 ? null : artifacts.length,
    null,
  );
  if (!artifacts.length) {
    result.body.appendChild(el(
      documentNode, "p", "empty", "No case evidence captured yet.",
    ));
  }
  for (const row of caseEvidence) {
    if (caseEvidence.length > 1) {
      result.body.appendChild(el(
        documentNode, "h3", "qa-group-label mono", row.case_key,
      ));
    }
    for (const artifact of row.artifacts) {
      result.body.appendChild(artifactEvidenceCard(context, artifact));
    }
  }
  return result.root;
}
