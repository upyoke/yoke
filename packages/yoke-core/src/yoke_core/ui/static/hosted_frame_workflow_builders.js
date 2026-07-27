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
    policies,
  };
  return {
    id,
    name,
    description,
    source: "built_in",
    status: "active",
    current_version: 1,
    published_at: "2026-07-20T12:00:00Z",
    versions: [{
      version: 1,
      definition_digest: `${id}-v1-fixture`,
      published_at: "2026-07-20T12:00:00Z",
      definition: structuredClone(definition),
    }],
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
