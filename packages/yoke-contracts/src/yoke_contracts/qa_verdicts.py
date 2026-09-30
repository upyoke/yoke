"""Shared QA verdict vocabulary for the CLI and server."""

UNDETERMINED_VERDICT = "undetermined"
VALID_VERDICTS = ("pass", "fail", UNDETERMINED_VERDICT, "error")

__all__ = ["UNDETERMINED_VERDICT", "VALID_VERDICTS"]
