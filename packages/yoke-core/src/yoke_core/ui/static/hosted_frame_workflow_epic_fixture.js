import {
  DELIVERY_POLICIES,
  gate,
  stage,
  workflow,
} from "./hosted_frame_workflow_builders.js";

export function hostedFrameEpicWorkflow() {
  return workflow({
    id: "epic",
    name: "Epic",
    description:
      "Planned task decomposition with parallel worktree lanes and an integration boundary.",
    entrySurfaces: ["harness_skill"],
    skills: [
      "refine", "shepherd", "refine", "conduct", "polish", "usher",
    ],
    stages: [
      stage("idea", "idea"),
      stage(
        "refining-idea",
        "refining idea",
        [gate("db_claim_prose"), gate("db_mutation", "joint")],
      ),
      stage(
        "refined-idea",
        "refined idea",
        [gate("db_claim_prose"), gate("architecture_impact")],
      ),
      stage(
        "planning",
        "planning",
        [gate("architecture_impact")],
        "The Architect decomposes the epic into tasks — file budgets, interface contracts, and worktree lanes.",
      ),
      stage(
        "plan-drafted",
        "plan drafted",
        [gate("architecture_impact")],
        "The task plan is drafted and awaits the refine pass before it can be committed.",
      ),
      stage(
        "refining-plan",
        "refining plan",
        [gate("architecture_impact")],
        "The plan is refined against the spec — simplify lenses and readiness repair — before it commits.",
      ),
      stage(
        "planned",
        "planned",
        [
          gate("db_claim_prose"),
          gate("architecture_impact"),
          gate("plan_simulation"),
        ],
        "The plan is committed and has passed the simulator; the tasks are ready to fan out into worktree lanes.",
      ),
      stage(
        "implementing",
        "implementing",
        [
          gate("check_hard_blocks"),
          gate("claim_activation"),
          gate("architecture_impact"),
        ],
        "Parallel task lanes execute against the plan, each in its own worktree, with the main session integrating.",
      ),
      stage(
        "reviewing-implementation",
        "reviewing implementation",
        [
          gate("db_claim_prose"),
          gate("db_mutation", "evidence"),
          gate("architecture_impact"),
        ],
        "Integrated task work is reviewed across the whole epic before the set can advance.",
      ),
      stage(
        "reviewed-implementation",
        "reviewed implementation",
        [
          gate("architecture_impact"),
          gate("path_claim_boundary"),
          gate("qa_verification"),
        ],
      ),
      stage(
        "polishing-implementation",
        "polishing implementation",
        [gate("architecture_impact")],
      ),
      stage(
        "implemented",
        "implemented",
        [
          gate("db_claim_prose"),
          gate("db_mutation", "polish"),
          gate("architecture_impact"),
          gate("path_claim_boundary"),
          gate("qa_verification"),
        ],
      ),
      stage(
        "release",
        "release",
        [
          gate("architecture_impact"),
          gate("path_claim_boundary"),
          gate("qa_verification"),
        ],
      ),
      stage(
        "done",
        "done",
        [gate("architecture_impact"), gate("qa_verification")],
        "Every task merged, integrated, and delivered; the epic closes.",
      ),
    ],
    policies: {
      ownership: "item_claim_and_task_lanes",
      ...DELIVERY_POLICIES,
      path_claims: "required_per_task",
      worktrees: "worker_and_integration_lanes",
      generated_children: "epic_tasks",
      qa: "project_and_task_attachments",
    },
  });
}
