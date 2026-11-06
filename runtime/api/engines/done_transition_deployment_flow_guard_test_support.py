# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import contextmanager

from types import SimpleNamespace

from unittest import mock

import pytest

from yoke_core.engines import (
    done_transition,
    done_transition_deploy_gates,
    done_transition_gates,
)


def _patch_registered_flows(flows):
    return mock.patch(
        "yoke_core.domain.deployment_flow_validator.list_registered_flow_ids",
        return_value=list(flows),
    )


def _patch_target_tier(value):
    return mock.patch.object(
        done_transition_deploy_gates,
        "_read_deployment_flow_target_tier",
        return_value=value,
    )


@contextmanager
def _patch_latest_run(status, run_id=""):
    with (
        mock.patch.object(
            done_transition_deploy_gates,
            "_get_latest_run_status",
            return_value=(status, run_id),
        ),
        mock.patch.object(
            done_transition_deploy_gates,
            "_read_delivery_evidence",
            return_value={"state": "not_discharged"},
        ),
    ):
        yield


def _patch_qa_gates(blocks):
    return mock.patch.object(
        done_transition_deploy_gates, "check_run_qa_gates", return_value=blocks
    )
