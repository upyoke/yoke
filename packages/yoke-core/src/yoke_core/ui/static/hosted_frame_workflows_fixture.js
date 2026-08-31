// Deterministic registry data for the hosted-frame development page. This is
// not product state: it lets the real browser renderer and CSS be reviewed
// when no machine-local universe is running.
import {
  DELIVERY_POLICIES,
  gate,
  stage,
  workflow,
} from "./hosted_frame_workflow_builders.js";
import { createHostedFrameWorkflowClient } from "./hosted_frame_workflow_client.js";
import {
  hostedFrameEpicWorkflow,
} from "./hosted_frame_workflow_epic_fixture.js";

const GATES = {
  db_claim_prose: {
    name: "DB claim consistency",
    description:
      "The item's declared DB claim must agree with what its own text describes — prose about migrations alongside a claim of none is refused.",
    source_kind: "status_gate",
    availability: "live",
  },
  db_mutation: {
    name: "Governed DB mutation",
    description:
      "A declared governed mutation must satisfy this point's check — joint: the strategy fits the project's breakage policy with no cross-item overlap; evidence: the authoritative apply evidence exists; polish: migration closeout is complete.",
    source_kind: "status_gate",
    availability: "live",
  },
  architecture_impact: {
    name: "Architecture impact",
    description:
      "The item's declared architecture impact must be resolved before it advances: an item still marked 'uncertain' is refused past refined-idea. Conformance to the project's architecture model itself is reported by the architecture Doctor checks, which hold the checkout this gate does not.",
    source_kind: "status_gate",
    availability: "live",
  },
  path_claim_boundary: {
    name: "Path-claim boundary",
    description:
      "The item's changed files must stay inside its registered path claims.",
    source_kind: "status_gate",
    availability: "live",
  },
  plan_simulation: {
    name: "Plan simulation",
    description:
      "The epic's plan must pass the simulator's cross-task execution trace.",
    source_kind: "status_gate",
    availability: "live",
  },
  conflict_survey: {
    name: "Conflict survey",
    description:
      "The agent reads claims, worktrees, and frontier items and aborts on any detected conflict.",
    source_kind: "status_gate",
    availability: "live",
  },
  qa_verification: {
    name: "QA requirements",
    description:
      "Every QA requirement materialized for this transition must be satisfied — passed or explicitly waived.",
    source_kind: "status_gate",
    availability: "live",
  },
  check_hard_blocks: {
    name: "Dependency hard blocks",
    description:
      "Every upstream item this one depends on must be finished before activation.",
    source_kind: "activation_operation",
    availability: "live",
  },
  claim_activation: {
    name: "Claim activation",
    description:
      "Registered path claims activate together with the worktree; a conflicting live claim refuses activation.",
    source_kind: "activation_operation",
    availability: "live",
  },
  work_claim_activation: {
    name: "Work-claim activation",
    description:
      "The executing session takes the exclusive work claim, and a " +
      "worktree when the worktrees policy requires one.",
    source_kind: "activation_operation",
    availability: "live",
  },
  doc_claim_activation: {
    name: "Execution-document claim",
    description:
      "The Blitz atomically claims its single execution document; an already-owned document refuses activation.",
    source_kind: "activation_operation",
    availability: "live",
  },
  doc_completion: {
    name: "Document completion",
    description:
      "The strategy document must record what was completed, what changed, what remains, the evidence, and the parent reconciliation.",
    source_kind: "status_gate",
    availability: "live",
  },
  dash_evidence: {
    name: "Result evidence",
    description:
      "The result and verification evidence must be recorded on the item, plus every check the item's knobs declared — an attached plan passed, an approval resolved.",
    source_kind: "status_gate",
    availability: "live",
  },
  approval: {
    name: "Approval",
    description:
      "The approval request declared for this transition must be resolved. A transition with no approving role or actor declared carries no approval obligation — the gate is absent until one exists, and each absence is recorded as WorkflowGateAbsent.",
    source_kind: "status_gate",
    availability: "live",
  },
};

function hostedFrameWorkflows() {
  return [
    workflow({
      id: "dash",
      name: "Dash",
      description:
        "A short instruction you file in seconds — filing is the spec; an agent executes it end-to-end.",
      entrySurfaces: ["web_form", "cli", "harness_skill", "promotion"],
      skills: ["dash"],
      stages: [
        stage("idea", "idea"),
        stage(
          "implementing",
          "implementing",
          [
            gate("work_claim_activation"),
            gate("conflict_survey"),
            gate("architecture_impact"),
          ],
          "The agent surveys for conflicts, takes a worktree, and executes the instruction in one pass.",
        ),
        stage(
          "reviewing-implementation",
          "reviewing implementation",
          [
            gate("db_claim_prose"),
            gate("db_mutation", "evidence"),
            gate("architecture_impact"),
          ],
          "The verification close — the agent self-checks, plus any case a tightened posture knob added.",
        ),
        stage(
          "done",
          "done",
          [
            gate("architecture_impact"),
            gate("dash_evidence"),
          ],
          "Result and verification evidence are recorded on the item; delivery, when enabled, ran as an after-merge action.",
        ),
      ],
      policies: {
        ownership: "exclusive_session_work_claim",
        path_claims: "optional",
        path_survey: "required",
        worktrees: "single_implementation_lane",
        generated_children: "none",
        qa: "optional_item_attachment",
        approvals: "none",
        delivery: "after_merge_action",
        item_posture_allowlist: [
          "verification", "path_claims", "path_survey",
          "approval_on_done", "deployment",
        ],
      },
    }),
    workflow({
      id: "blitz",
      name: "Blitz",
      description:
        "Execute a strategy document directly; the item is only its coordination shell. Releases happen continuously inside implementing; the close reconciles the document.",
      entrySurfaces: ["harness_skill"],
      skills: ["refine", "blitz"],
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
          "implementing",
          "implementing",
          [
            gate("doc_claim_activation"),
            gate("conflict_survey"),
            gate("architecture_impact"),
          ],
          "The continuous slice loop — the linked document is executed directly, and each slice may merge, migrate, and deploy; there is no separate release stage.",
        ),
        stage(
          "reviewing-implementation",
          "reviewing implementation",
          [
            gate("db_claim_prose"),
            gate("db_mutation", "evidence"),
            gate("architecture_impact"),
          ],
          "The once-per-item close — the full suite runs and the document records what was completed, what changed, what remains, the evidence, and how the parent strategy was reconciled.",
        ),
        stage(
          "done",
          "done",
          [
            gate("architecture_impact"),
            gate("qa_verification"),
            gate("doc_completion"),
          ],
          "The execution document states completion and parent reconciliation; that evidence is the entry gate.",
        ),
      ],
      policies: {
        ownership: "session_item_and_document_claim",
        path_claims: "optional",
        path_survey: "required",
        worktrees: "worker_lanes_optional_integration",
        generated_children: "none",
        qa: "item_attachments",
        approvals: "optional_named_gate",
        delivery: "continuous_slice_actions",
        item_posture_allowlist: [
          "verification", "path_claims", "path_survey", "approval", "deployment",
        ],
      },
    }),
    workflow({
      id: "issue",
      name: "Issue",
      description:
        "One scoped implementation lane with planning, review, QA and delivery.",
      entrySurfaces: ["harness_skill", "promotion"],
      skills: ["refine", "advance", "polish", "usher"],
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
          "implementing",
          "implementing",
          [
            gate("check_hard_blocks"),
            gate("claim_activation"),
            gate("architecture_impact"),
          ],
          "One implementation lane in an isolated worktree; the engineer builds against the spec and acceptance criteria.",
        ),
        stage(
          "reviewing-implementation",
          "reviewing implementation",
          [
            gate("db_claim_prose"),
            gate("db_mutation", "evidence"),
            gate("architecture_impact"),
          ],
          "The in-worktree review loop — the work is checked against the acceptance criteria before it can leave the lane.",
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
          "Merged and delivered through the selected flow; the item closes.",
        ),
      ],
      policies: {
        ownership: "single_item_claim",
        ...DELIVERY_POLICIES,
      },
    }),
    hostedFrameEpicWorkflow(),
  ];
}

export function hostedFrameWorkflowClient() {
  return createHostedFrameWorkflowClient(hostedFrameWorkflows(), GATES);
}
