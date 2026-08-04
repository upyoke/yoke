"""The published canon is literal data, pinned, and immune to current drift."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_canon import (
    CANON_DIR,
    canon_digests,
    canon_generations,
    recognize,
)
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definitions,
)

# Canon is pinned two ways, and both must fail in CI rather than at fleet boot
# -- which is where a change to history failed twice.
#
# The fingerprint covers every generation's digest, in order, so editing any
# published definition moves it. The counts say how many generations each
# workflow has. Canon is append-only: appending updates both deliberately,
# and nothing else ever should.
PINNED_CANON_GENERATION_COUNTS = {
    "issue": 5,
    "epic": 5,
    "blitz": 7,
    "dash": 7,
}

PINNED_CANON_FINGERPRINT = (
    "1bf4af7f47229e1b577faa8b37882a968285a4b8122f278bd9ac13ca322e7747"
)


def _canon_fingerprint() -> str:
    """One hash over every (workflow, version, digest) triple, in order."""
    material = "\n".join(
        f"{g.workflow_id}.{g.canon_version:02d}={g.digest}"
        for g in canon_generations()
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def test_every_workflow_has_canon() -> None:
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        assert canon_generations(workflow_id), f"{workflow_id} has no canon"


def test_canon_generation_counts_are_pinned() -> None:
    """Appending a generation is deliberate; it updates this pin."""
    actual = {w: len(canon_generations(w)) for w in BUILTIN_WORKFLOW_IDS}
    assert actual == PINNED_CANON_GENERATION_COUNTS


def test_canon_fingerprint_is_pinned() -> None:
    """Editing any published definition moves this hash.

    This is the guard the old model lacked: history was rebuilt from current,
    so a field added to a current definition silently rewrote a historical
    digest and the failure surfaced at fleet boot instead of in CI.
    """
    assert _canon_fingerprint() == PINNED_CANON_FINGERPRINT


def test_canon_versions_are_dense_and_ordered() -> None:
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        versions = [g.canon_version for g in canon_generations(workflow_id)]
        assert versions == list(range(1, len(versions) + 1))


def test_canon_digests_are_distinct_within_a_workflow() -> None:
    """Two generations with one digest would mean a duplicate publish."""
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        digests = canon_digests(workflow_id)
        assert len(set(digests)) == len(digests)


def test_recognition_is_by_digest_not_version_number() -> None:
    """The property that lets universes publish on their own schedules."""
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        for generation in canon_generations(workflow_id):
            found = recognize(workflow_id, generation.digest)
            assert found is not None
            assert found.canon_version == generation.canon_version


def test_unknown_digest_is_not_recognized() -> None:
    assert recognize("issue", "0" * 64) is None


def test_current_definition_is_the_newest_canon_generation() -> None:
    """Shipping a new current definition means appending it to canon."""
    for fixture in builtin_workflow_definitions():
        workflow_id = str(fixture["workflow"]["id"])
        from yoke_core.domain.workflow_definition_codec import definition_digest

        assert recognize(workflow_id, definition_digest(fixture["definition"])) is not None, (
            f"{workflow_id}'s current definition is not in canon; "
            "append it as the next generation"
        )


def test_mutating_a_current_definition_moves_no_canon_digest() -> None:
    """The invariant that would have caught both outages.

    History used to be reconstructed by subtracting remembered fields from the
    current definition, so adding a field to current silently changed a
    historical digest and the fleet refused to boot. Canon is literal data
    loaded from disk; mutating current must not move it.
    """
    before = {w: canon_digests(w) for w in BUILTIN_WORKFLOW_IDS}

    for fixture in builtin_workflow_definitions():
        definition = fixture["definition"]
        definition["stages"][0]["a_field_a_future_author_adds"] = "value"
        definition["policies"]["a_policy_a_future_author_adds"] = "value"

    after = {w: canon_digests(w) for w in BUILTIN_WORKFLOW_IDS}
    assert after == before


def test_canon_files_are_valid_json_with_required_keys() -> None:
    for path in sorted(CANON_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workflow_id", "canon_version", "published_at", "definition"):
            assert key in payload, f"{path.name} missing {key}"


def test_canon_definitions_are_caller_owned() -> None:
    """A caller mutating what it got back must not corrupt the canon."""
    first = canon_generations("issue")[0]
    original = deepcopy(first.definition)
    generations = canon_generations("issue")
    assert generations[0].definition == original


@pytest.mark.parametrize("workflow_id", BUILTIN_WORKFLOW_IDS)
def test_canon_is_structurally_readable(workflow_id: str) -> None:
    """Canon must be readable, not currently-authorable.

    The current validator describes what an author may write today; history is
    older than it by construction. Real published generations carry
    ``executor_bindings``, which today's schema rejects outright. Validating
    canon against the current schema therefore fails on genuine history -- and
    boot convergence does exactly that, which reconstruction hid because a
    reconstructed fixture always inherited current's vocabulary.
    """
    for generation in canon_generations(workflow_id):
        definition = generation.definition
        assert isinstance(definition.get("stages"), list) and definition["stages"]
        assert isinstance(definition.get("policies"), dict)
        assert isinstance(definition.get("schema_version"), int)


@pytest.mark.parametrize("workflow_id", BUILTIN_WORKFLOW_IDS)
def test_current_definition_validates(workflow_id: str) -> None:
    """What must satisfy the current schema is the current definition."""
    from yoke_core.domain.workflow_definition_validation import (
        validate_workflow_definition,
    )

    for fixture in builtin_workflow_definitions():
        if str(fixture["workflow"]["id"]) == workflow_id:
            validate_workflow_definition(fixture["definition"])
