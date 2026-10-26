"""Help descriptions for launch operations whose outcome needs explaining."""

from __future__ import annotations


LAUNCH_CANCEL_DESCRIPTION = (
    "Cancel one session launch. A launch whose session has registered but "
    "not yet received its instructions ends that session too: it is "
    "terminated, its claims released, and one native-process reap queued. "
    "A delivered launch whose registered session has ended is settled as "
    "cancelled_session_ended. If that session is still live, cancel refuses "
    "launch_session_working; end it "
    'deliberately with `yoke sessions terminate SESSION-ID --reason "<why>"`. '
    "A failed unregistered launch with recorded native exit evidence is settled "
    "by cancel and leaves the steering report; its diagnostic evidence is retained. "
    "A launch whose native process exists but has no recorded exit moves to "
    "outcome_unknown (cancellation_requires_reconciliation); resolve it with "
    "`yoke session-control launch reconcile LAUNCH-ID`. A cancelled launch is "
    "final: reconcile never revives it."
)

_ROUTING = (
    "Omit selection flags: Yoke routes by the item's workflow stage level, "
    "then picks surface, model, effort and machine. --level, --surface and "
    "--machine are overrides; when to use each: "
    ".yoke/docs/agents/level-launches.md#overrides."
)

LAUNCH_PREVIEW_DESCRIPTION = (
    f"With --item, preview the route `launch create --item` takes. {_ROUTING}"
)

LAUNCH_CREATE_DESCRIPTION = _ROUTING


def _examples(verb: str, level_flags: str, key: str) -> str:
    base = f"yoke session-control launch {verb} --project P --item PREFIX-N"
    return (
        "examples:\n"
        "  Default: the item's stage level decides\n"
        f"    {base}{key}\n"
        "  Level override: the work needs a level other than the stage level\n"
        f"    {base} {level_flags}{key}\n"
        "  Placement override: a refusal names one, or the operator asks\n"
        f"    {base} --surface S --model M --reasoning-effort E{key}\n"
    )


LAUNCH_PREVIEW_EXAMPLES = _examples("preview", "--level LEVEL", "")
LAUNCH_CREATE_EXAMPLES = _examples(
    "create", '--level LEVEL --level-reason "<why>"', " --idempotency-key K"
)

#: Operation name -> help description, where the usage line alone is not enough.
LAUNCH_DESCRIPTIONS = {"cancel": LAUNCH_CANCEL_DESCRIPTION}

__all__ = [
    "LAUNCH_CANCEL_DESCRIPTION",
    "LAUNCH_CREATE_DESCRIPTION",
    "LAUNCH_CREATE_EXAMPLES",
    "LAUNCH_DESCRIPTIONS",
    "LAUNCH_PREVIEW_DESCRIPTION",
    "LAUNCH_PREVIEW_EXAMPLES",
]
