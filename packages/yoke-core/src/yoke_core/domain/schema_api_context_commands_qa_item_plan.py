"""``qa`` topic wrapper-command recipes for item plan retraction.

Sibling of :mod:`schema_api_context_commands_qa`. Split out so that
module stays under the authored-file line cap while this write still
reaches the merged ``WRAPPER_COMMANDS`` export.
"""

from __future__ import annotations


QA_ITEM_PLAN_COMMANDS: list[dict] = [
    {
        "startup_roles": (),
        "topic": "qa",
        "purpose": "Retract a mis-specified item plan attachment",
        "recipe": (
            "yoke qa item-plan retract --item PREFIX-N --project P "
            "--plan-id N --transition T --reason TEXT"
        ),
        "notes": (
            "Registered write qa.item_plan.retract. Withdraws a standing "
            "attachment at any phase that should not have been made. The "
            "attachment row stays, marked retracted. Requirements it "
            "materialized retire as retracted — not waived, not superseded. "
            "Release admission and frozen selection skip withdrawn "
            "requirements and member attachments. Repeating this write "
            "retires copies older builds created after withdrawal, preserves "
            "the original attachment record, and still refuses executed "
            "copies. Re-drive the run or execute its member-scoped QA stage "
            "afterward; a replacement plan still needs its own evidence. "
            "After retraction the item is unanswered again: attach a "
            "corrected plan, or record that no post-deploy obligation "
            "exists with `yoke qa post-deploy record-no-obligation`. "
            "Silence still blocks. Any recorded run or verdict refuses with "
            "attachment_has_recorded_run; preserve execution evidence and "
            "use yoke qa requirement waive or supersede --help for settlement. "
            "Re-attaching the same retracted (item, transition, plan) is "
            "refused so the history row remains. Wrong guesses: that "
            "waiver or supersession is how you undo a wrong attachment, "
            "and that retracting is how you discard an unwelcome fail."
        ),
    },
]


__all__ = ["QA_ITEM_PLAN_COMMANDS"]
