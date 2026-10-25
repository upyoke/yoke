"""Explicit commit observations preserve the verified identity and evidence."""

import json
import pytest
from yoke_core.domain.qa_run_commit_binding import bind_recorded_raw_result, wrap_evidence
from yoke_core.domain.qa_merging_identity import recorded_head_sha


@pytest.mark.parametrize("raw", [None, "passed", '{"evidence":{"lease":17}}'])
def test_no_explicit_commit_leaves_evidence_unchanged(raw):
    assert bind_recorded_raw_result(raw_result=raw) == raw


def test_explicit_commit_preserves_prose():
    raw = bind_recorded_raw_result(raw_result="passed", head_sha="a" * 40)
    assert recorded_head_sha(raw) == "a" * 40
    assert json.loads(raw)["evidence"] == "passed"


@pytest.mark.parametrize("raw", [wrap_evidence("passed", "a" * 40), '{"code_identity":{"sha":"served"}}'])
def test_explicit_commit_never_overwrites_verified_identity(raw):
    assert bind_recorded_raw_result(raw_result=raw, head_sha="b" * 40) == raw
