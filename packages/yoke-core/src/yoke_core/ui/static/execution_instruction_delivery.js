import { el } from "./universe_view_support.js";

const DELIVERY_POINTS = [
  ["before_creation", "Before creation"],
  ["on_every_read", "On every read"],
  ["when_entering_stage", "When entering stage"],
];
const STAGE_BUCKETS = [
  "idea", "planning", "refined", "implementing", "reviewing", "implemented", "release",
];

// Missing read fields use the serving build's previous delivery behavior.
export function instructionDelivery(instruction) {
  return {
    before_creation: instruction.before_creation ?? true,
    on_every_read: instruction.on_every_read ?? true,
    when_entering_stage: instruction.when_entering_stage ?? false,
    stage_buckets: [...(instruction.stage_buckets || [])],
  };
}

export function instructionDeliveryHint(instruction) {
  const delivery = instructionDelivery(instruction);
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

export function deliveryControls(documentNode, delivery, checkboxRow) {
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
  for (const bucket of STAGE_BUCKETS) {
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
