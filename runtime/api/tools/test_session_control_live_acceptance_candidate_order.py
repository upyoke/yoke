"""Ordering contract for stage-only private-route candidate proofs."""

from runtime.api.tools.session_control_live_acceptance_contract import (
    parse_candidate_matrix,
)


def test_candidate_matrix_runs_every_surface_before_any_broker() -> None:
    parsed = parse_candidate_matrix(
        {
            "schema": 2,
            "project": "yoke",
            "cells": [
                {
                    "surface": "claude-cli",
                    "expected_version": "2.1.241",
                    "mode": "identify",
                    "session_id": "broker-target",
                    "machine_id": "machine-1",
                    "acceptance_role": "broker",
                    "wake_route": "broker",
                    "broker_session_id": "broker-peer",
                },
                {
                    "surface": "claude-desktop",
                    "expected_version": "1.34493.1",
                    "mode": "identify",
                    "session_id": "desktop-target",
                    "acceptance_role": "surface",
                    "wake_route": "none",
                },
            ],
        }
    )

    assert tuple((cell.surface, cell.acceptance_role) for cell in parsed.cells) == (
        ("claude-desktop", "surface"),
        ("claude-cli", "broker"),
    )
