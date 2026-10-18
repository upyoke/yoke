"""The refusal raised when carried enrollment cannot admit one item.

Enrollment admits carried items in item order and stops at the first one it
cannot admit. The items after it are never attempted, so the omission check
that runs next must say enrollment stopped there rather than guess why they
are missing. This error carries the item and its cause for that reader.
"""

from __future__ import annotations


class CarriedEnrollmentError(ValueError):
    """A carried item enrollment could not admit; enrollment stopped there."""

    def __init__(self, run_id: str, item_ref: str, cause: Exception) -> None:
        self.item_ref = item_ref
        self.cause = str(cause)
        super().__init__(
            f"deployment run {run_id!r} carries {item_ref} but cannot admit it: "
            f"{self.cause}; repair what that names (for a flow or stage "
            "mismatch, align the item's deployment flow and stage with this "
            "run), or choose a candidate that excludes its code"
        )

    def omission_reason(self) -> str:
        """Why the items enrollment never reached are missing."""
        return (
            f"enrollment stopped at {self.item_ref}, which it could not admit: "
            f"{self.cause}"
        )


__all__ = ["CarriedEnrollmentError"]
