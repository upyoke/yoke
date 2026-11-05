# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime

from pathlib import Path

from unittest import mock

from yoke_contracts.api.function_call import FunctionCallResponse

from yoke_contracts.timestamps import parse_instant

from yoke_core.engines import done_transition

from yoke_core.engines import done_transition_status


def _patch_run_internals(repo_root, **overrides):
    """Return an ExitStack context that patches all done_transition internals.

    Shared helper for tests that exercise run() without hitting real git/DB.
    ``overrides`` can replace individual return values or callable side effects
    by function name.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    patches = [
        ("_resolve_repo_root", repo_root),
        ("_resolve_project_context", (repo_root, "")),
        ("_get_base_branch", "main"),
        ("_check_merge_guard", True),
        ("_check_blocked_flag", None),
        ("_verify_recovery_evidence", True),
        ("_check_empty_branch", None),
        ("_cleanup_stale_branches", True),
        ("_verify_cwd_after_merge", repo_root),
        ("_schema_gate", None),
        ("_check_deployment_flow_guard", None),
        ("_populate_merged_at", None),
        ("_update_status_to_done", True),
        ("_finalize_done_local_side_effects", None),
        ("_update_item_direct", 0),
        ("_run_git", mock.Mock(return_value=mock.Mock(returncode=0, stdout=""))),
    ]
    for attr, default in patches:
        override = overrides.get(attr, default)
        if isinstance(override, mock.Mock):
            stack.enter_context(mock.patch.object(done_transition, attr, override))
        elif callable(override):
            stack.enter_context(
                mock.patch.object(done_transition, attr, side_effect=override)
            )
        else:
            stack.enter_context(
                mock.patch.object(done_transition, attr, return_value=override)
            )
    return stack
