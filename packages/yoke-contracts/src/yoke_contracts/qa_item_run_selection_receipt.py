"""Prove a server honoured the run an item's holder named.

``--item PREFIX-N --stage S --deployment-run-id RUN`` sends the run as the
``deployment_run_id`` argument. A server below its floor may ignore an
argument it does not know and resolve some other run, so every receipt is
checked: the answering run must be the one requested.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.function_argument_floors import declared_argument_floors

ARGUMENT = "deployment_run_id"


def selected_run_mismatch(
    function_id: str, requested: str, receipt: Mapping[str, Any] | None
) -> str | None:
    """The refusal text when *receipt* does not attest *requested*, else None."""
    body = dict(receipt or {})
    # Materialize receipts wrap their answer in ``result``; begin's is flat.
    if isinstance(body.get("result"), Mapping):
        body = dict(body["result"])
    answered = str(body.get(ARGUMENT) or "")
    if answered == str(requested):
        return None
    floor = declared_argument_floors(function_id, {ARGUMENT: requested}).get(ARGUMENT)
    version = floor.minimum_serving_version if floor else "next-release"
    form = f" Until then use {floor.older_form}." if floor else ""
    return (
        f"function_argument_version_skew: {function_id} did not attest run "
        f"{requested} (receipt names {answered or 'no run'}); item QA with "
        f"--deployment-run-id requires minimum serving version {version}.{form} "
        "Inspect what the server wrote with `yoke deployment-runs get "
        f"{answered or requested}` before retrying."
    )


__all__ = ["ARGUMENT", "selected_run_mismatch"]
