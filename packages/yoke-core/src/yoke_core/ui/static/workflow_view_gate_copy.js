import {
  workflowStageDisplayLabel,
} from "./workflow_view_primitives.js";

function inlineCodeToken(value, token) {
  const text = String(value || "");
  const index = text.indexOf(token);
  if (index < 0) return text;
  return [
    text.slice(0, index),
    { kind: "code", text: token },
    text.slice(index + token.length),
  ];
}

function sentenceList(values) {
  if (values.length < 2) return values[0] || "";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

function gateStageNames(workflow, gateId) {
  return (workflow.definition?.stages || [])
    .filter((stage) =>
      (stage.gates || []).some((gateRef) => gateRef.id === gateId))
    .map((stage) => workflowStageDisplayLabel(workflow, stage));
}

export function gateDescription(workflow, gate) {
  const description = gate.id === "architecture_impact"
    ? inlineCodeToken(gate.description, "architecture_model")
    : gate.description;
  const stages = gateStageNames(workflow, gate.id);
  if (stages.length < 2) return description;

  const parts = [
    {
      kind: "strong",
      className: "workflow-gate-reassertion",
      text: "Re-asserted invariant.",
    },
    ` The same rule is re-checked on entry to ${sentenceList(stages)}.`,
  ];
  if (!description) return parts;
  return [
    ...parts,
    " ",
    ...(Array.isArray(description) ? description : [description]),
  ];
}
