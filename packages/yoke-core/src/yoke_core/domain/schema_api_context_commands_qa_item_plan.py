"""``qa`` topic wrapper-command recipes for item plan attach and retract.

Sibling of :mod:`schema_api_context_commands_qa`. Split out so that
module stays under the authored-file line cap while this write still
reaches the merged ``WRAPPER_COMMANDS`` export.
"""

from __future__ import annotations


QA_ITEM_PLAN_COMMANDS: list[dict] = [
    {
        "topic": "qa",
        "purpose": "Retract a mis-specified item plan attachment",
        "recipe": (
            "yoke qa item-plan retract --item PREFIX-N --project P "
            "--plan-id N --transition T --reason TEXT"
        ),
        "notes": (
            "Registered write qa.item_plan.retract. Withdraws a standing "
            "post-deploy attachment that should not have been made. The "
            "attachment row stays, marked retracted. Requirements it "
            "materialized retire as retracted — not waived, not superseded. "
            "After retraction the item is unanswered again: attach a "
            "corrected plan, or record that no post-deploy obligation "
            "exists with `yoke qa post-deploy record-no-obligation`. "
            "Silence still blocks. A verification-phase attachment cannot "
            "be retracted here; a post-deploy case that already passed "
            "refuses, because that would rewrite settled delivery evidence. "
            "Re-attaching the same retracted (item, transition, plan) is "
            "refused so the history row remains. Wrong guesses: that "
            "waiver or supersession is how you undo a wrong attachment, "
            "and that retracting is how you discard an unwelcome fail."
        ),
    },
    {
        "topic": "qa",
        "purpose": "Attach a QA plan at a transition the item can satisfy",
        "recipe": (
            "yoke qa item-plan attach --item PREFIX-N --project P "
            "--plan-id N --transition T [--qa-phase PHASE] "
            "[--acknowledge-unreachable-target]"
        ),
        "notes": (
            "Registered write qa.item_plan.attach. A plan with no "
            "target_environment_id attaches at any transition it does "
            "today. A plan bound to a persistent environment attached at "
            "a transition that precedes delivery to that environment is "
            "refused: the revision probe resolves from that target, so "
            "the requirement can never pass and the item cannot enter "
            "release. The refusal names the post-deploy attachment that "
            "works. Pass acknowledge_unreachable_target only when the "
            "caller knows the target is already reachable. Wrong guesses: "
            "that --base-url can redirect a bound revision probe, and "
            "that verification posture can select an environment-bound "
            "plan."
        ),
    },
]


__all__ = ["QA_ITEM_PLAN_COMMANDS"]
