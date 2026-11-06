# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from types import SimpleNamespace

import pytest

from runtime.api.merge_queue_landing_test_helpers import land, wire_happy_path

from yoke_core.domain import merge_queue_live_drift as drift_mod

from yoke_core.domain import merge_queue_route as route_mod

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestTransportError,
)

from yoke_core.domain.merge_queue_live_drift import (
    DRIFT_SKIP_DECLARATION_MISSING,
    DRIFT_SKIP_DECLARATION_UNREADABLE,
    DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED,
    DRIFT_SKIP_GITHUB_UNREACHABLE,
    LiveDriftReport,
    compare_declared_against_live,
    drift_blocking_landing,
    enforcement_drift,
    live_branch_rules,
)

DECLARED = {
    "schema": 1,
    "repository": {"allow_auto_merge": True},
    "ruleset": {
        "name": "merge-queue-main",
        "rules": [
            {"type": "merge_queue", "parameters": {"merge_method": "MERGE"}},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": "shard-1"}],
                },
            },
        ],
    },
}


def _live_rules(contexts):
    return [
        {
            "type": "merge_queue",
            "parameters": {"merge_method": "MERGE"},
            "ruleset_id": 20658925,
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
                "required_status_checks": [{"context": name} for name in contexts],
            },
        },
    ]
