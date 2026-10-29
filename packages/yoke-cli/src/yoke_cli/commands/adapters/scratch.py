"""Client-local dispatch input path adapter."""

from __future__ import annotations
import argparse
import importlib
from typing import List
from yoke_cli.commands._helpers import parse_or_usage_error, usage_error

SCRATCH_DISPATCH_INPUTS_USAGE = (
    "yoke scratch dispatch-inputs PREFIX-N SESSION-ID ATTEMPT [--project P] [--full]"
)


def scratch_dispatch_inputs(args: List[str]) -> int:
    """Print the helper-resolved dispatch-inputs absolute path.

    Resolves the path locally via
    :func:`yoke_core.domain.project_scratch_dir.dispatch_inputs_dir`
    (no HTTP roundtrip — the shepherd skill's ``$(...)`` capture is the
    canonical caller and shell-recipe latency would dominate). The
    grammar-rule function id is ``scratch.dispatch_inputs``; the
    matching CLI tokens are ``("scratch", "dispatch-inputs")``.

    Output contract: exactly one line on stdout, the absolute path,
    terminated by a single ``\\n``. Stderr is reserved for errors.
    """

    import sys

    scratch_dir = importlib.import_module("yoke_core.domain.project_scratch_dir")
    parser = argparse.ArgumentParser(
        prog="yoke scratch dispatch-inputs",
        usage=SCRATCH_DISPATCH_INPUTS_USAGE,
        description=(
            "Create, if needed, the dispatch inputs folder for one item, session\n"
            "and attempt, and print its absolute path as one line. Runs on this\n"
            "machine only."
        ),
    )
    parser.add_argument("item", metavar="PREFIX-N", help="The item.")
    parser.add_argument("session_id", metavar="SESSION-ID", help="The harness session id.")
    parser.add_argument("attempt", metavar="ATTEMPT", help="The dispatch attempt number, starting at 1.")
    parsed = parse_or_usage_error(parser, args, SCRATCH_DISPATCH_INPUTS_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_contracts.public_ref import parse_public_item_ref

        prefix, sequence = parse_public_item_ref(parsed.item)
        if prefix is None or sequence is None:
            raise ValueError("public_item_ref_required: pass PREFIX-N")
    except ValueError as exc:
        return usage_error(str(exc))
    try:
        attempt = int(parsed.attempt)
    except ValueError:
        return usage_error("attempt must be an integer")
    if attempt < 1:
        return usage_error("attempt must be >= 1")
    if not parsed.session_id.strip():
        return usage_error("session_id must be non-empty")

    from yoke_cli.config.project_selection import required_project_context
    from yoke_contracts.project_defaults import MissingProjectError

    try:
        project = required_project_context(parsed.project)
    except MissingProjectError as exc:
        return usage_error(str(exc))
    path = scratch_dir.dispatch_inputs_dir(
        project, parsed.item, parsed.session_id, attempt
    )
    sys.stdout.write(f"{path}\n")
    sys.stdout.flush()
    return 0
