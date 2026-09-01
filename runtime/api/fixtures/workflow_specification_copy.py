"""The workflow and gate copy the product specification owns.

Held apart from the tests that assert it so the prose reads as one
reviewable document rather than as scattered string literals.
"""

from __future__ import annotations

EXPECTED_WORKFLOW_COPY = {
    "dash": {
        "description": (
            "A short instruction you file in seconds — filing is the spec; "
            "an agent executes it end-to-end."
        ),
        "stages": {
            "implementing": (
                "The agent surveys for conflicts, takes a worktree, and "
                "executes the instruction in one pass."
            ),
            "reviewing-implementation": (
                "The verification close — the agent self-checks, plus any "
                "case a tightened posture knob added."
            ),
            "done": (
                "Result and verification evidence are recorded on the item; "
                "delivery, when enabled, ran as an after-merge action."
            ),
        },
    },
    "blitz": {
        "description": (
            "Execute a strategy document directly; the item is only its "
            "coordination shell. Releases happen continuously inside "
            "implementing; the close reconciles the document."
        ),
        "stages": {
            "implementing": (
                "The continuous slice loop — the linked document is executed "
                "directly, and each slice may merge, migrate, and deploy; "
                "there is no separate release stage."
            ),
            "reviewing-implementation": (
                "The once-per-item close — the full suite runs and the "
                "document records what was completed, what changed, what "
                "remains, the evidence, and how the parent strategy was "
                "reconciled."
            ),
            "done": (
                "The execution document states completion and parent "
                "reconciliation; that evidence is the entry gate."
            ),
        },
    },
    "issue": {
        "description": (
            "One scoped implementation lane with planning, review, QA and delivery."
        ),
        "stages": {
            "implementing": (
                "One implementation lane in an isolated worktree; the "
                "engineer builds against the spec and acceptance criteria."
            ),
            "reviewing-implementation": (
                "The in-worktree review loop — the work is checked against "
                "the acceptance criteria before it can leave the lane."
            ),
            "done": (
                "Merged and delivered through the selected flow; the item closes."
            ),
        },
    },
    "epic": {
        "description": (
            "Planned task decomposition with parallel worktree lanes and an "
            "integration boundary."
        ),
        "stages": {
            "planning": (
                "The Architect decomposes the epic into tasks — file budgets, "
                "interface contracts, and worktree lanes."
            ),
            "plan-drafted": (
                "The task plan is drafted and awaits the refine pass before "
                "it can be committed."
            ),
            "refining-plan": (
                "The plan is refined against the spec — simplify lenses and "
                "readiness repair — before it commits."
            ),
            "planned": (
                "The plan is committed and has passed the simulator; the "
                "tasks are ready to fan out into worktree lanes."
            ),
            "implementing": (
                "Parallel task lanes execute against the plan, each in its "
                "own worktree, with the main session integrating."
            ),
            "reviewing-implementation": (
                "Integrated task work is reviewed across the whole epic "
                "before the set can advance."
            ),
            "done": ("Every task merged, integrated, and delivered; the epic closes."),
        },
    },
    "task": {
        "description": (
            "A floor workflow for folder-only and non-code work — idea, "
            "implementing, done; no git lane, no merge, done is the floor "
            "attestation."
        ),
        "stages": {
            "implementing": (
                "The executing session takes the exclusive work claim and "
                "performs the work without a git lane."
            ),
            "done": (
                "The floor attestation is recorded — the agent account plus "
                "observed changes, with no merge SHA required."
            ),
        },
    },
}

EXPECTED_GATE_DESCRIPTIONS = {
    "db_claim_prose": (
        "The item's declared DB claim must agree with what its own text "
        "describes — prose about migrations alongside a claim of none is "
        "refused."
    ),
    "db_mutation": (
        "A declared governed mutation must satisfy this point's check — "
        "joint: the strategy fits the project's breakage policy with no "
        "cross-item overlap; evidence: the authoritative apply evidence "
        "exists; polish: migration closeout is complete."
    ),
    "architecture_impact": (
        "The item's declared architecture impact must be resolved before it "
        "advances: an item still marked 'uncertain' is refused past refined-idea. "
        "Conformance to the project's architecture model itself is reported by "
        "the architecture Doctor checks, which hold the checkout this gate does not."
    ),
    "path_claim_boundary": (
        "The item's changed files must stay inside its registered path "
        "claims, diffed against the highest reachable rung of the "
        "integration ladder — the remote integration ref, else the "
        "local one. An item with no claims is clear; an item with "
        "claims and no worktree, or no resolvable ref, is refused."
    ),
    "plan_simulation": (
        "The epic's plan must pass the simulator's cross-task execution trace."
    ),
    "qa_verification": (
        "Every QA requirement materialized for this transition must be "
        "satisfied — passed or explicitly waived."
    ),
    "check_hard_blocks": (
        "Every upstream item this one depends on must be finished before activation."
    ),
    "claim_activation": (
        "Registered path claims activate together with the worktree; a "
        "conflicting live claim refuses activation."
    ),
    "work_claim_activation": (
        "The executing session takes the exclusive work claim, and a "
        "worktree when the worktrees policy requires one."
    ),
    "doc_claim_activation": (
        "The Blitz atomically claims its single execution document; an "
        "already-owned document refuses activation."
    ),
    "conflict_survey": (
        "The agent reads claims, worktrees, and frontier items and aborts on "
        "any detected conflict."
    ),
    "doc_completion": (
        "The strategy document must record what was completed, what changed, "
        "what remains, the evidence, and the parent reconciliation."
    ),
    "dash_evidence": (
        "The result and verification evidence must be recorded on the item, "
        "plus every check the item's knobs declared — an attached plan "
        "passed, an approval resolved."
    ),
    "floor_attestation": (
        "Done is the recorded floor attestation — the agent account "
        "plus observed changes, stamped agent-attested, with no "
        "merge SHA required."
    ),
}

__all__ = ["EXPECTED_GATE_DESCRIPTIONS", "EXPECTED_WORKFLOW_COPY"]
