"""Each harness manifest states its parallel sub-agent fact from one contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.harness_subagent_capability import (
    HARNESS_SUBAGENT_CAPABILITIES,
    subagent_capability_for_harness,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST_DIRS = {"claude-code": "claude", "codex": "codex", "cursor": "cursor"}


@pytest.mark.parametrize("harness_id", sorted(MANIFEST_DIRS))
def test_rendered_manifest_carries_the_contract_entry(harness_id):
    manifest = json.loads(
        (
            REPO / "runtime" / "harness" / MANIFEST_DIRS[harness_id] / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    rendered = manifest["parallel_subagents"]
    expected = HARNESS_SUBAGENT_CAPABILITIES[harness_id].to_json()
    assert {key: rendered[key] for key in expected} == expected
    assert rendered["source"].endswith("HARNESS_SUBAGENT_CAPABILITIES")


@pytest.mark.parametrize("harness_id", sorted(HARNESS_SUBAGENT_CAPABILITIES))
def test_supported_entries_name_mechanism_and_surface(harness_id):
    entry = HARNESS_SUBAGENT_CAPABILITIES[harness_id]
    assert entry.evidence
    if entry.parallel_subagents == "supported":
        assert entry.mechanism and entry.verified_on_surface
    else:
        assert not entry.mechanism


def test_unknown_harness_is_unverified():
    entry = subagent_capability_for_harness("not-a-harness")
    assert entry.parallel_subagents == "unverified"
    assert "HARNESS_SUBAGENT_CAPABILITIES" in entry.evidence
