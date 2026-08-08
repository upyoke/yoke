// Deterministic sample data for the workflows-page prototype. This is not
// product state and no engine or API is involved: the prototype renders this
// so the redesign can be reviewed on a laptop before anything is built.

const STAGE_IDS = {
  dash: ["idea", "implementing", "reviewing-implementation", "done"],
  blitz: [
    "idea", "refining-idea", "refined-idea", "implementing",
    "reviewing-implementation", "done",
  ],
  issue: [
    "idea", "refining-idea", "refined-idea", "implementing",
    "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation", "implemented", "release", "done",
  ],
  epic: [
    "idea", "refining-idea", "refined-idea", "planning", "plan-drafted",
    "refining-plan", "planned", "implementing", "reviewing-implementation",
    "reviewed-implementation", "polishing-implementation", "implemented",
    "release", "done",
  ],
};

const DESCRIPTIONS = {
  dash:
    "A short instruction you file in seconds — filing is the spec; an agent " +
    "executes it end-to-end.",
  blitz:
    "Execute a strategy document directly; the item is only its coordination " +
    "shell. Releases happen continuously inside implementing.",
  issue: "One scoped implementation lane with planning, review, QA and delivery.",
  epic:
    "Planned task decomposition with parallel worktree lanes and an " +
    "integration boundary.",
};

// Sparse: only the stages that check something on entry. Everything else
// reads as "nothing is checked on entry", which is a real product state.
const GATES = {
  dash: {
    implementing: ["conflict_survey", "work_claim_activation"],
    "reviewing-implementation": ["qa_verification"],
    done: ["dash_evidence", "path_claim_boundary"],
  },
  blitz: {
    "refined-idea": ["architecture_impact", "db_claim_prose"],
    implementing: ["conflict_survey"],
    done: ["qa_verification"],
  },
  issue: {
    "refined-idea": ["architecture_impact", "db_claim_prose"],
    implementing: ["conflict_survey", "work_claim_activation"],
    "reviewing-implementation": ["qa_verification"],
    release: ["db_mutation"],
    done: ["path_claim_boundary"],
  },
  epic: {
    "refined-idea": ["architecture_impact"],
    planned: ["plan_simulation"],
    implementing: ["conflict_survey"],
    "reviewing-implementation": ["qa_verification"],
    done: ["path_claim_boundary"],
  },
};

// Current-version policies. Note what is absent: there is no parallelism key
// anywhere. Nothing in the engine ever read it, so the redesign drops it and
// derives lane topology from worktrees plus child items instead.
const POLICIES = {
  dash: {
    ownership: "exclusive_session_work_claim",
    file_budget: "optional",
    path_claims: "optional",
    path_survey: "required",
    worktrees: "single_implementation_lane",
    generated_children: "none",
    qa: "optional_item_attachment",
    approvals: "none",
    delivery: "after_merge_action",
    item_posture_allowlist: [
      "verification", "file_budget", "path_claims", "path_survey",
      "approval_on_done", "deployment",
    ],
  },
  blitz: {
    ownership: "session_item_and_document_claim",
    file_budget: "optional",
    path_claims: "optional",
    path_survey: "required",
    worktrees: "worker_lanes_optional_integration",
    generated_children: "none",
    qa: "item_attachments",
    approvals: "optional_named_gate",
    delivery: "continuous_slice_actions",
    item_posture_allowlist: [
      "verification", "file_budget", "path_claims", "path_survey",
    ],
  },
  issue: {
    ownership: "single_item_claim",
    file_budget: "required",
    path_claims: "required",
    worktrees: "single_implementation_lane",
    generated_children: "none",
    qa: "project_transition_defaults",
    approvals: "definition_transitions",
    delivery: "release_stage",
    item_posture_allowlist: ["verification"],
  },
  epic: {
    ownership: "item_claim_and_task_lanes",
    file_budget: "required_per_task",
    path_claims: "required_per_task",
    worktrees: "worker_and_integration_lanes",
    generated_children: "epic_tasks",
    qa: "project_and_task_attachments",
    approvals: "definition_transitions",
    delivery: "release_stage",
    item_posture_allowlist: ["verification"],
  },
};

const SKILLS = {
  dash: ["dash"],
  blitz: ["refine", "blitz"],
  issue: ["refine", "advance", "polish", "usher"],
  epic: ["refine", "shepherd", "conduct", "polish", "usher"],
};

function stages(id) {
  return STAGE_IDS[id].map((stageId) => ({
    id: stageId,
    label: stageId,
    gates: (GATES[id][stageId] || []).map((gateId) => ({ id: gateId })),
  }));
}

function definition(id, policies) {
  return {
    schema_version: 4,
    stages: stages(id),
    entry_surfaces: id === "dash"
      ? ["web_form", "cli", "harness_skill", "promotion"]
      : ["harness_skill", "promotion"],
    skill_bindings: SKILLS[id].map((skillId) => ({
      skill_id: skillId,
      from_stage_id: STAGE_IDS[id][0],
      through_stage_id: STAGE_IDS[id].at(-1),
    })),
    policies,
  };
}

// Walking the history backwards one published version at a time. Each step
// undoes something a real version introduced, so every row has a delta to
// show and the oldest versions genuinely predate keys the newest declares.
const BACK_STEPS = [
  function removeTerminalGate(value) {
    const terminal = value.stages.at(-1);
    if (terminal.gates.length) terminal.gates = terminal.gates.slice(0, -1);
  },
  function dropPathSurvey(value) {
    delete value.policies.path_survey;
    value.policies.item_posture_allowlist = value.policies
      .item_posture_allowlist.filter((entry) => entry !== "path_survey");
  },
  function narrowEntrySurfaces(value) {
    value.entry_surfaces = value.entry_surfaces
      .filter((surface) => surface !== "promotion");
  },
  function dropFileBudget(value) {
    delete value.policies.file_budget;
    value.policies.item_posture_allowlist = value.policies
      .item_posture_allowlist.filter((entry) => entry !== "file_budget");
  },
  function removeReviewGate(value) {
    const review = value.stages
      .find((stage) => stage.id === "reviewing-implementation");
    if (review && review.gates.length) review.gates = review.gates.slice(0, -1);
  },
  function loosenOwnership(value) {
    value.policies.ownership = "single_item_claim";
  },
];

// Oldest first, so index i is version i+1.
function definitionLadder(id, count) {
  const ladder = [definition(id, POLICIES[id])];
  for (let step = 0; step < count - 1; step += 1) {
    const older = structuredClone(ladder[0]);
    BACK_STEPS[step % BACK_STEPS.length](older);
    ladder.unshift(older);
  }
  return ladder;
}

const PUBLISHED = [
  "2026-05-04T11:00:00Z", "2026-05-27T09:30:00Z", "2026-06-15T16:10:00Z",
  "2026-07-02T13:45:00Z", "2026-07-19T10:05:00Z", "2026-07-28T15:20:00Z",
  "2026-08-06T08:40:00Z",
];

// Each entry is one published, immutable version: what it says, when it
// landed, where it came from, and how many live items are pinned to it.
function versions(id, count, current, pinned, local) {
  const ladder = definitionLadder(id, count);
  return ladder.map((value, index) => {
    const version = index + 1;
    const latest = version === count;
    return {
      version,
      published_at: PUBLISHED[index],
      definition_digest: `${id}-v${version}-1f3c9a77b2e4`,
      definition: value,
      provenance: local && latest
        ? { kind: "local", derived_from_canon_version: count - 1 }
        : { kind: "canon", canon_version: version },
      pinned_item_count: pinned[index] ?? 0,
      made_current_at: version === current && version !== count
        ? "2026-08-02T09:15:00Z"
        : null,
    };
  });
}

export const PROTOTYPE_WORKFLOWS = [
  {
    id: "dash",
    name: "Dash",
    source: "built_in",
    description: DESCRIPTIONS.dash,
    current_version: 7,
    canon_follow: "auto",
    definition: definition("dash", POLICIES.dash),
    versions: versions("dash", 7, 7, [0, 0, 0, 2, 1, 6, 14], false),
    canon_status: { state: "up_to_date" },
    // Auto-follow adopted this on its own; the notice reports it after the
    // fact rather than asking for a decision nobody needed to make.
    adopted: { version: 7, at: "2026-08-06T08:40:00Z" },
  },
  {
    id: "blitz",
    name: "Blitz",
    source: "built_in",
    description: DESCRIPTIONS.blitz,
    current_version: 6,
    canon_follow: "manual",
    definition: definition("blitz", POLICIES.blitz),
    versions: versions("blitz", 6, 6, [0, 0, 1, 0, 3, 5], true),
    canon_status: {
      state: "customized_update_available",
      derived_from_canon_version: 5,
      latest_canon_version: 7,
    },
    adopted: null,
  },
  {
    id: "issue",
    name: "Issue",
    source: "built_in",
    description: DESCRIPTIONS.issue,
    current_version: 5,
    canon_follow: "auto",
    definition: definition("issue", POLICIES.issue),
    versions: versions("issue", 5, 5, [0, 1, 4, 7, 23], false),
    canon_status: { state: "up_to_date" },
    adopted: null,
  },
  {
    id: "epic",
    name: "Epic",
    source: "built_in",
    description: DESCRIPTIONS.epic,
    // Rolled back: v5 exists and is readable, but v4 is what new items pin.
    current_version: 4,
    canon_follow: "auto",
    definition: definition("epic", POLICIES.epic),
    versions: versions("epic", 5, 4, [0, 0, 2, 9, 0], false),
    canon_status: { state: "up_to_date" },
    adopted: null,
  },
];

// Operator-authored execution instructions. Title, ordering and status are
// gone: an instruction is its content, its workflows and its projects.
export const PROTOTYPE_INSTRUCTIONS = [
  {
    id: 4,
    content:
      "Never widen a work item's scope to absorb an adjacent bug. File it " +
      "separately and link it, so the two land on their own evidence.",
    applies_to_all_workflows: true,
    workflow_ids: [],
    applies_to_all_projects: true,
    project_ids: [],
  },
  {
    id: 7,
    content:
      "Before merging, re-read the item's acceptance criteria one at a time " +
      "and name the evidence for each. A criterion with no named evidence is " +
      "not met.",
    applies_to_all_workflows: false,
    workflow_ids: ["issue", "epic", "dash"],
    applies_to_all_projects: false,
    project_ids: [1],
  },
  {
    id: 9,
    content:
      "Dash instructions are the whole spec. If the work needs crafted " +
      "acceptance criteria, stop and escalate rather than inventing them.",
    applies_to_all_workflows: false,
    workflow_ids: ["dash"],
    applies_to_all_projects: true,
    project_ids: [],
  },
  {
    id: 11,
    content:
      "Reconcile the strategy document at close: every slice it promised is " +
      "either shipped, dropped with a reason, or carried forward by name.",
    applies_to_all_workflows: false,
    workflow_ids: [],
    applies_to_all_projects: true,
    project_ids: [],
  },
];

export const PROTOTYPE_PROJECTS = [
  { id: 1, slug: "yoke" },
  { id: 2, slug: "buzz" },
  { id: 3, slug: "platform" },
];
