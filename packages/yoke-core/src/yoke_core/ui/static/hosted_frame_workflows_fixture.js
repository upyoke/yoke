// Deterministic registry data for the hosted-frame development page. This is
// not product state: it lets the real browser renderer and CSS be reviewed
// when no machine-local universe is running.

const GATES = {
  architecture_impact: {
    name: "Architecture impact",
    description:
      "The declared impact must honor the project's architecture model.",
    source_kind: "status_gate",
  },
  conflict_survey: {
    name: "Conflict survey",
    description:
      "Claims, worktrees, and frontier items are checked before execution.",
    source_kind: "activation_op",
  },
  qa_verification: {
    name: "QA requirements",
    description:
      "Every requirement for this transition must pass or be waived.",
    source_kind: "status_gate",
  },
  dash_evidence: {
    name: "Result evidence",
    description:
      "The result and every item-declared check must be recorded.",
    source_kind: "status_gate",
  },
};

function gate(id) {
  return { id };
}

function stage(id, label, gates = [], description = "") {
  const value = { id, label, gates };
  if (description) value.description = description;
  return value;
}

function workflow({
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

const DELIVERY_POLICIES = {
  path_claims: "required",
  worktrees: "single_implementation_lane",
  parallelism: "inside_item",
  generated_children: "none",
  qa: "project_transition_defaults",
  approvals: "definition_transitions",
  delivery: "release_stage",
  item_posture_allowlist: ["verification", "approval", "deployment"],
};

function hostedFrameWorkflows() {
  return [
    workflow({
      id: "dash",
      name: "Dash",
      description:
        "A short instruction you file in seconds — filing is the spec; an agent executes it end-to-end.",
      entrySurfaces: ["web_form", "cli", "harness_skill", "promotion"],
      executors: ["dash"],
      stages: [
        stage("idea", "Idea"),
        stage(
          "implementing",
          "Implementing",
          [gate("conflict_survey"), gate("architecture_impact")],
          "The executor surveys conflicts and completes the instruction.",
        ),
        stage(
          "reviewing-implementation",
          "Reviewing implementation",
          [gate("architecture_impact")],
          "The executor self-checks plus any declared verification.",
        ),
        stage(
          "done",
          "Done",
          [
            gate("architecture_impact"),
            gate("qa_verification"),
            gate("dash_evidence"),
          ],
          "The result and verification evidence are recorded on the item.",
        ),
      ],
      policies: {
        ownership: "exclusive_session_work_claim",
        path_claims: "optional",
        worktrees: "single_implementation_lane",
        parallelism: "none",
        generated_children: "none",
        qa: "optional_item_attachment",
        approvals: "none",
        delivery: "after_merge_action",
        item_posture_allowlist: [
          "verification", "path_claims", "approval_on_done", "deployment",
        ],
      },
    }),
    workflow({
      id: "blitz",
      name: "Blitz",
      description:
        "Execute a strategy document directly; the item is only its coordination shell.",
      entrySurfaces: ["harness_skill"],
      executors: ["refine", "blitz"],
      stages: [
        stage("idea", "Idea"),
        stage("refining-idea", "Refining idea"),
        stage("refined-idea", "Refined idea"),
        stage(
          "implementing",
          "Implementing",
          [gate("conflict_survey"), gate("architecture_impact")],
          "The linked document drives a continuous loop of integrated slices.",
        ),
        stage("reviewing-implementation", "Reviewing implementation"),
        stage("done", "Done", [gate("qa_verification")]),
      ],
      policies: {
        ownership: "session_item_and_document_claim",
        path_claims: "optional",
        worktrees: "worker_lanes_optional_integration",
        parallelism: "maximum_safe_slices",
        generated_children: "none",
        qa: "item_attachments",
        approvals: "optional_named_gate",
        delivery: "continuous_slice_actions",
        item_posture_allowlist: [
          "verification", "path_claims", "approval", "deployment",
        ],
      },
    }),
    workflow({
      id: "issue",
      name: "Issue",
      description:
        "One scoped implementation lane with planning, review, QA and delivery.",
      entrySurfaces: ["harness_skill", "promotion"],
      executors: ["refine", "advance", "polish", "usher"],
      stages: [
        stage("idea", "Idea"),
        stage("refining-idea", "Refining idea"),
        stage("refined-idea", "Refined idea"),
        stage("implementing", "Implementing"),
        stage("reviewing-implementation", "Reviewing implementation"),
        stage("reviewed-implementation", "Reviewed implementation"),
        stage("polishing-implementation", "Polishing implementation"),
        stage("implemented", "Implemented"),
        stage("release", "Release", [gate("qa_verification")]),
        stage("done", "Done"),
      ],
      policies: {
        ownership: "single_item_claim",
        ...DELIVERY_POLICIES,
      },
    }),
    workflow({
      id: "epic",
      name: "Epic",
      description:
        "Planned task decomposition with parallel lanes and an integration boundary.",
      entrySurfaces: ["harness_skill"],
      executors: ["refine", "shepherd", "conduct", "polish", "usher"],
      stages: [
        stage("idea", "Idea"),
        stage("refining-idea", "Refining idea"),
        stage("refined-idea", "Refined idea"),
        stage("planning", "Planning"),
        stage("plan-drafted", "Plan drafted"),
        stage("refining-plan", "Refining plan"),
        stage("planned", "Planned"),
        stage("implementing", "Implementing"),
        stage("reviewing-implementation", "Reviewing implementation"),
        stage("reviewed-implementation", "Reviewed implementation"),
        stage("polishing-implementation", "Polishing implementation"),
        stage("implemented", "Implemented"),
        stage("release", "Release", [gate("qa_verification")]),
        stage("done", "Done"),
      ],
      policies: {
        ownership: "item_claim_and_task_lanes",
        ...DELIVERY_POLICIES,
        path_claims: "required_per_task",
        worktrees: "worker_and_integration_lanes",
        parallelism: "task_graph",
        generated_children: "epic_tasks",
        qa: "project_and_task_attachments",
      },
    }),
  ];
}

export function hostedFrameWorkflowClient() {
  const workflows = hostedFrameWorkflows();
  const ok = (result) => ({
    status: 200,
    envelope: { success: true, result },
  });
  return {
    async call(request) {
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "workflows.definition.get") {
        return ok({
          family: "work-items",
          workflows: structuredClone(workflows),
          gate_catalog: Object.entries(GATES).map(([id, value]) => ({
            id,
            availability: "live",
            ...value,
          })),
          flows: [],
        });
      }
      if (request.function === "workflows.version.get") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        const version = current?.versions.find(
          (row) => Number(row.version) === Number(request.payload.version),
        );
        if (current && version) {
          return ok({
            workflow_id: current.id,
            ...structuredClone(version),
            current:
              Number(current.current_version) === Number(version.version),
            definition: structuredClone(version.definition),
          });
        }
      }
      if (request.function === "workflows.policy_defaults.publish") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        if (current) {
          const version =
            Math.max(...current.versions.map((row) => Number(row.version))) + 1;
          const publishedAt = new Date().toISOString();
          const definition = structuredClone(current.definition);
          definition.policies.path_claims =
            request.payload.path_claims_default ? "required" : "optional";
          current.current_version = version;
          current.published_at = publishedAt;
          current.definition = definition;
          current.versions.push({
            version,
            definition_digest: `${current.id}-v${version}-fixture`,
            published_at: publishedAt,
            definition: structuredClone(definition),
          });
          return ok({
            workflow_id: current.id,
            version,
            version_id: version,
            definition_digest: `${current.id}-v${version}-fixture`,
            path_claims_default: request.payload.path_claims_default,
          });
        }
      }
      if (request.function === "workflows.current.set") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        if (current) {
          const version = current.versions.find(
            (row) => Number(row.version) === Number(request.payload.version),
          );
          if (!version) {
            return {
              status: 404,
              envelope: {
                success: false,
                error: { message: "Workflow version not found." },
              },
            };
          }
          current.current_version = Number(version.version);
          current.published_at = version.published_at;
          current.definition = structuredClone(version.definition);
          return ok({
            workflow_id: current.id,
            version: current.current_version,
            version_id: current.current_version,
          });
        }
      }
      return {
        status: 404,
        envelope: {
          success: false,
          error: { message: `No fixture for ${request.function}` },
        },
      };
    },
  };
}
