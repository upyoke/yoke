const FIRST_PUBLISHED_AT = "2026-07-20T12:00:00Z";
const CURRENT_PUBLISHED_AT = "2026-07-27T12:00:00Z";

const VERSION_ONE_STAGE_DESCRIPTIONS = {
  issue: {
    implementing:
      "One implementation lane builds against the item's acceptance criteria.",
    "reviewing-implementation": null,
    done: "The item is merged, delivered, and closed.",
  },
  epic: {
    planning: "The plan is decomposed into tasks, interfaces, budgets, and lanes.",
    "plan-drafted": null,
    "refining-plan": null,
    planned: "The committed task plan has passed cross-task simulation.",
    implementing:
      "Task lanes execute in parallel and the main session integrates them.",
    "reviewing-implementation": null,
    done: "Every task is integrated, delivered, and closed.",
  },
  blitz: {
    implementing:
      "The linked document drives a continuous loop of integrated slices.",
    "reviewing-implementation":
      "The complete result and its evidence are reconciled in the document.",
    done: "The document records completion and parent reconciliation.",
  },
  dash: {
    implementing: "The executor surveys conflicts and completes the instruction.",
    "reviewing-implementation":
      "The executor self-checks plus any item-declared verification.",
    done: "The result and verification evidence are recorded on the item.",
  },
};

function versionOneDefinition(workflowId, currentDefinition) {
  const definition = structuredClone(currentDefinition);
  delete definition.policies.approval_defaults;
  if (["blitz", "dash"].includes(workflowId)) {
    delete definition.policies.path_survey;
    definition.policies.item_posture_allowlist = (
      definition.policies.item_posture_allowlist || []
    ).filter((key) => key !== "path_survey");
  }
  const descriptions = VERSION_ONE_STAGE_DESCRIPTIONS[workflowId] || {};
  for (const workflowStage of definition.stages) {
    workflowStage.label =
      `${workflowStage.label.slice(0, 1).toUpperCase()}${workflowStage.label.slice(1)}`;
    if (!Object.hasOwn(descriptions, workflowStage.id)) continue;
    const description = descriptions[workflowStage.id];
    if (description) workflowStage.description = description;
    else delete workflowStage.description;
  }
  return definition;
}

export function gate(id, mode = null) {
  return mode ? { id, mode } : { id };
}

export function stage(id, label, gates = [], description = "") {
  const value = { id, label, gates };
  if (description) value.description = description;
  return value;
}

export function workflow({
  id,
  name,
  description,
  stages,
  entrySurfaces,
  executors,
  policies,
}) {
  const definition = {
    stages,
    entry_surfaces: entrySurfaces,
    executor_bindings: executors.map((executorId) => ({
      executor_id: executorId,
    })),
    policies: {
      ...policies,
      approval_defaults: structuredClone(policies.approval_defaults || {}),
    },
  };
  const historicalDefinition = versionOneDefinition(id, definition);
  return {
    id,
    name,
    description,
    source: "built_in",
    status: "active",
    current_version: 2,
    published_at: CURRENT_PUBLISHED_AT,
    versions: [
      {
        version: 1,
        definition_digest: `${id}-v1-fixture`,
        published_at: FIRST_PUBLISHED_AT,
        published_by_actor_id: null,
        definition: historicalDefinition,
      },
      {
        version: 2,
        definition_digest: `${id}-v2-fixture`,
        published_at: CURRENT_PUBLISHED_AT,
        published_by_actor_id: null,
        definition: structuredClone(definition),
      },
    ],
    definition,
  };
}

export const DELIVERY_POLICIES = {
  path_claims: "required",
  worktrees: "single_implementation_lane",
  parallelism: "inside_item",
  generated_children: "none",
  qa: "project_transition_defaults",
  approvals: "definition_transitions",
  delivery: "release_stage",
  item_posture_allowlist: ["verification", "approval", "deployment"],
};
