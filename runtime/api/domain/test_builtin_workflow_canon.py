"""The published canon is literal data, pinned, and immune to current drift."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

from yoke_core.domain.builtin_workflow_canon import (
    CANON_DIR,
    CanonGeneration,
    canon_digests,
    canon_generations,
    recognize,
)
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definitions,
)
from yoke_core.domain.workflow_definition_codec import definition_digest

# Canon is pinned two ways, and both must fail in CI rather than at fleet boot
# -- which is where a change to history failed twice.
#
# The fingerprint covers every generation's digest, in order, so editing any
# published definition moves it. The counts say how many generations each
# workflow has. Canon is append-only: appending updates both deliberately,
# and nothing else ever should.
PINNED_CANON_GENERATION_COUNTS = {
    "issue": 10,
    "epic": 8,
    "blitz": 12,
    "dash": 13,
    "task": 4,
}

PINNED_CANON_FINGERPRINT = (
    "7426f14fcd72c52a5d138243ff65f647072f1b85b7cffab9e61c40d53c6f78ca"
)


def _canon_fingerprint() -> str:
    """One hash over every (workflow, version, digest) triple, in order."""
    material = "\n".join(
        f"{g.workflow_id}.{g.canon_version:02d}={g.digest}" for g in canon_generations()
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
    """Shipping a new current definition means appending it to canon.

    Newest, not merely present: the dashboard reports "up to date" by
    comparing a universe's current definition against the last generation, so
    a current definition sitting at an older one would tell every universe it
    was behind something it already had.
    """
    for fixture in builtin_workflow_definitions():
        workflow_id = str(fixture["workflow"]["id"])
        generation = recognize(workflow_id, definition_digest(fixture["definition"]))
        assert generation is not None, (
            f"{workflow_id}'s current definition is not in canon; "
            "append it as the next generation"
        )
        newest = canon_generations(workflow_id)[-1]
        assert generation.canon_version == newest.canon_version, (
            f"{workflow_id}'s current definition is canon generation "
            f"{generation.canon_version}, but {newest.canon_version} is newer"
        )
        assert fixture["canon_version"] == newest.canon_version


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


@pytest.mark.parametrize(
    "clock",
    [
        parse_instant("1969-12-31T23:59:59.123456Z"),
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
    ],
)
def test_canon_publication_ingress_is_native_without_changing_definition(clock):
    payload = json.loads(next(iter(sorted(CANON_DIR.glob("*.json")))).read_text())
    payload["published_at"] = clock
    before = deepcopy(payload)
    generation = CanonGeneration(payload)
    assert isinstance(generation.published_at, datetime)
    assert generation.published_at == parse_instant("1969-12-31T23:59:59.123456Z")
    assert generation.digest == definition_digest(before["definition"])
    assert payload == before


@pytest.mark.parametrize(
    "bad", [None, "", "1969-12-31", "1969-12-31T23:59:59", datetime(1969, 12, 31)]
)
def test_canon_publication_ingress_refuses_missing_or_ambiguous_clock(bad):
    payload = json.loads(next(iter(sorted(CANON_DIR.glob("*.json")))).read_text())
    payload["published_at"] = bad
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        CanonGeneration(payload)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_historical_generation_fixture_binds_native_publication_clock(
    test_db, monkeypatch, zone
):
    from runtime.api import workflow_version_test_helpers as fixtures

    archived = next(
        generation
        for generation in canon_generations("dash")
        if "file_budget" not in generation.definition["policies"]
    )
    clock = parse_instant("1969-12-31T23:59:59.123456Z")
    generation = CanonGeneration(
        {
            "workflow_id": archived.workflow_id,
            "canon_version": archived.canon_version,
            "published_at": clock,
            "definition": deepcopy(archived.definition),
        }
    )
    monkeypatch.setattr(
        fixtures, "canon_generations", lambda workflow_id: (generation,)
    )
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    version_id, _ = fixtures.seed_generation_lacking_file_budget(test_db)
    row = test_db.execute(
        "SELECT published_at, immutable_at, definition_digest, "
        "pg_typeof(published_at)::text, pg_typeof(immutable_at)::text "
        "FROM workflow_versions WHERE id=%s",
        (version_id,),
    ).fetchone()
    assert tuple(row) == (
        clock,
        clock,
        archived.digest,
        "timestamp with time zone",
        "timestamp with time zone",
    )
