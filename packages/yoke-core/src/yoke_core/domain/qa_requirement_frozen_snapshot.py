"""The refusal shared by every in-place edit of a frozen QA requirement.

Both requirement-update paths -- the case content in
:mod:`qa_requirement_config_update` and the target identity in
:mod:`qa_requirement_target_env_update` -- refuse with the same code and
the same recovery, so the code and its message live here rather than in
either caller.
"""

from __future__ import annotations


FROZEN_REQUIREMENT_CODE = "frozen_requirement_immutable"
FROZEN_REQUIREMENT_MESSAGE = (
    "frozen_requirement_immutable: a deployment-run requirement is a frozen "
    "acceptance snapshot and cannot be corrected in place. Update the live "
    "item requirement, then re-run it. Recovery: yoke qa requirement update "
    "--requirement-id <live-id> --field method_config --value '<json>'"
)


__all__ = ["FROZEN_REQUIREMENT_CODE", "FROZEN_REQUIREMENT_MESSAGE"]
