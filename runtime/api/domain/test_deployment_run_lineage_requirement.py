"""Refusing a deployment run at creation when its flow will demand lineage.

Observed live: creation returned a run id, the operator drove it, and
execution walked two stages before refusing. The run had to be abandoned
and recreated. Every case here is about moving that refusal to the point
where nothing has happened yet.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_run_lineage_requirement as lineage

_SHA = "79a6816839f8df9eac5cbdfdd528e6c1f9fd3915"
_DISPATCH = [
    {"name": "merged", "step_runner": "auto"},
    {"name": "hosted-release", "step_runner": lineage.DISPATCHING_STEP_RUNNER},
    {"name": "complete", "step_runner": "auto"},
]
_NO_DISPATCH = [
    {"name": "merged", "step_runner": "auto"},
    {"name": "complete", "step_runner": "auto"},
]


def test_a_dispatching_stage_anywhere_in_the_flow_is_detected():
    """Derived from the stages, not from a roster of flow ids.

    A flow that later gains a dispatch stage inherits the requirement
    without anyone remembering to update a list.
    """
    assert lineage.stages_dispatch_a_workflow(_DISPATCH)


def test_a_flow_with_no_dispatch_stage_needs_nothing():
    assert not lineage.stages_dispatch_a_workflow(_NO_DISPATCH)
    lineage.require_lineage_for_stages(_NO_DISPATCH, None, flow="internal")


@pytest.mark.parametrize("stages", [[], None, [None, "junk", 7]])
def test_malformed_or_absent_stages_never_raise(stages):
    """Creation must not fail on a shape the caller cannot control."""
    assert not lineage.stages_dispatch_a_workflow(stages)


def test_a_missing_lineage_is_refused_and_names_the_binding_flags():
    """The operator has a repo in front of them and needs the recipe."""
    with pytest.raises(lineage.LineageRequiredError) as excinfo:
        lineage.require_lineage_for_stages(_DISPATCH, None, flow="hosted-stage")
    message = str(excinfo.value)
    assert "hosted-stage" in message
    assert "--project-repo-path" in message
    assert "--source-ref" in message
    assert "fail at execution" in message


def test_an_empty_lineage_is_treated_as_missing():
    with pytest.raises(lineage.LineageRequiredError):
        lineage.require_lineage_for_stages(_DISPATCH, "   ")


def test_a_full_sha_satisfies_the_requirement():
    lineage.require_lineage_for_stages(_DISPATCH, _SHA)
    assert lineage.looks_immutable(_SHA)


def test_an_annotated_release_tag_satisfies_the_requirement():
    """Accepted here and re-checked at dispatch.

    Creation has no remote to ask whether a tag is annotated, and refusing
    every tag would block the release train's own historical shape.
    """
    lineage.require_lineage_for_stages(_DISPATCH, "v0.1.1+launch.185")


@pytest.mark.parametrize("moving", ["main", "master", "HEAD", "origin/main"])
def test_a_branch_ref_is_refused_as_moving(moving):
    """The whole point of the requirement is that the ref cannot move."""
    assert not lineage.looks_immutable(moving)
    with pytest.raises(lineage.LineageRequiredError) as excinfo:
        lineage.require_lineage_for_stages(_DISPATCH, moving)
    assert "moving ref" in str(excinfo.value)


def test_a_short_sha_is_refused_as_ambiguous():
    assert not lineage.looks_immutable(_SHA[:12])


def test_the_refusal_names_the_flow_when_known_and_omits_it_otherwise():
    with pytest.raises(lineage.LineageRequiredError) as named:
        lineage.require_lineage_for_stages(_DISPATCH, None, flow="some-flow")
    assert "'some-flow'" in str(named.value)

    with pytest.raises(lineage.LineageRequiredError) as anonymous:
        lineage.require_lineage_for_stages(_DISPATCH, None)
    assert "''" not in str(anonymous.value)
