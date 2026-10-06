import { el } from "./universe_view_support.js";

const DELIVERY_POINTS = [
  ["before_creation", "Before creation"],
  ["on_every_read", "On every read"],
  ["when_entering_stage", "When entering stage"],
];
// Stage buckets and new-instruction defaults are served by
// workflow.execution_instruction.list as `delivery_options`; the UI keeps no copy.
export const DELIVERY_OPTIONS_UNAVAILABLE =
  "delivery_options_unavailable: the serving build's instruction list returned no "
  + "delivery_options, so delivery cannot be edited here. Deploy a Yoke build "
  + "that serves them, or use `yoke workflow execution-instruction update`.";

/** The instruction's delivery, with fields it omits taken from the served defaults. */
export function instructionDelivery(instruction, options) {
  const defaults = options?.defaults || {};
  return {
    before_creation: instruction.before_creation ?? defaults.before_creation,
    on_every_read: instruction.on_every_read ?? defaults.on_every_read,
    when_entering_stage: instruction.when_entering_stage ?? defaults.when_entering_stage,
    stage_buckets: [...(instruction.stage_buckets ?? defaults.stage_buckets ?? [])],
  };
}

export function instructionDeliveryHint(instruction, options) {
  const delivery = instructionDelivery(instruction, options);
  return DELIVERY_POINTS.filter(([key]) => delivery[key]).map(([key, label]) =>
    key === "when_entering_stage"
      ? `${label}: ${delivery.stage_buckets.join(", ")}` : label,
  ).join(" · ");
}

export function deliveryValidationError(delivery) {
  if (!DELIVERY_POINTS.some(([key]) => delivery[key])) {
    return "delivery_point_required: select Before creation, On every read, or When entering stage.";
  }
  if (delivery.when_entering_stage && !delivery.stage_buckets.length) {
    return "stage_bucket_required: select at least one stage bucket for When entering stage.";
  }
  return "";
}

export function deliveryControls(documentNode, delivery, options, checkboxRow) {
  const group = el(documentNode, "fieldset", "instruction-delivery");
  group.appendChild(el(documentNode, "legend", "workflow-field-label", "Delivery"));
  group.appendChild(el(
    documentNode, "p", "workflow-field-help", "Select at least one delivery point.",
  ));
  const points = el(documentNode, "div", "instruction-checkbox-group");
  const bucketInputs = [];
  const syncBuckets = () => {
    for (const input of bucketInputs) input.disabled = !delivery.when_entering_stage;
  };
  for (const [key, label] of DELIVERY_POINTS) {
    points.appendChild(checkboxRow(
      documentNode, delivery[key], label, `instruction-${key.replaceAll("_", "-")}`,
      (event) => { delivery[key] = event.target.checked; syncBuckets(); },
    ).row);
  }
  group.appendChild(points);
  const buckets = el(documentNode, "fieldset", "instruction-stage-buckets");
  buckets.appendChild(el(documentNode, "legend", "workflow-field-label", "Stage buckets"));
  buckets.appendChild(el(
    documentNode, "p", "workflow-field-help",
    "When entering stage requires at least one bucket. These instructions also appear on item reads while the item is in a selected bucket.",
  ));
  const choices = el(documentNode, "div", "instruction-checkbox-group");
  for (const bucket of options.stage_buckets) {
    const member = checkboxRow(
      documentNode, delivery.stage_buckets.includes(bucket), bucket,
      "instruction-stage-bucket-checkbox",
      (event) => {
        delivery.stage_buckets = event.target.checked
          ? [...delivery.stage_buckets, bucket]
          : delivery.stage_buckets.filter((value) => value !== bucket);
      },
    );
    bucketInputs.push(member.input);
    choices.appendChild(member.row);
  }
  syncBuckets();
  buckets.appendChild(choices);
  group.appendChild(buckets);
  return group;
}
