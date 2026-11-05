# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_contracts.api.function_call import TargetRef

from yoke_core.domain import deployment_runs_validation as validation

from yoke_core.domain.deployment_run_item_qa_membership import (
    NO_MEMBER_OWES_TARGET,
    item_qa_membership_verdict,
    memberless_item_qa_refusal,
    owed_delivery_item_ids,
)

from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

from yoke_core.domain.handlers.deployment_run_execution import (
    handle_deployment_execution_context,
)


def _isolate_candidate_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold every candidate walk still so only the item-QA verdict varies."""
    for name, value in (
        ("record_bound_sources", lambda *_a, **_k: None),
        ("resolve_candidate_custody", lambda *_a, **_k: None),
        ("carried_enrollment_blocked", lambda *_a, **_k: "test-fixture"),
        ("enroll_carried_members", lambda *_a, **_k: ()),
        ("carried_project_ids", lambda *_a, **_k: (1,)),
        ("carried_membership_refusal", lambda *_a, **_k: ""),
        ("unclosable_final_member_refusal", lambda *_a, **_k: ""),
        ("unadmitted_post_deploy_notice", lambda *_a, **_k: ""),
        ("inert_membership_notice", lambda *_a, **_k: ""),
        ("skipped_candidate_verdict", lambda *_a, **_k: ("", "")),
    ):
        monkeypatch.setattr(validation, name, value)
