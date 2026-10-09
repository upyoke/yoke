"""Credential intent and archive diagnostic clocks preserve file evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_source_authority_credential_cutoff import _bundle
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import universe_archive_validation as archive

WIRE = "2026-07-14T00:00:00.123456Z"
CLOCK = parse_instant(WIRE)
OFFSET = "2026-07-14T05:45:00.123456+05:45"
BAD = [None, "", "now", "2026-07-14T00:00:00", CLOCK.replace(tzinfo=None)]


@pytest.mark.parametrize("clock", [CLOCK, OFFSET])
def test_new_retirement_intent_formats_clock_and_retry_keeps_exact_file(
    tmp_path, clock
):
    bundle = _bundle(tmp_path)
    prepared = credentials.prepare_retirement(
        bundle, retirement_receipt="opaque", retired_at=clock
    )
    original = bundle.path.read_bytes()
    assert prepared.retired_at == WIRE
    assert json.loads(original)["retirement"]["retired_at"] == WIRE
    repeated = credentials.prepare_retirement(
        bundle, retirement_receipt="opaque", retired_at=OFFSET
    )
    assert repeated.retired_at == WIRE
    assert bundle.path.read_bytes() == original


@pytest.mark.parametrize("clock", BAD)
def test_invalid_retirement_clock_refuses_before_file_access(clock, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("file read preceded instant validation")

    monkeypatch.setattr(credentials, "load_bound", unexpected)
    with pytest.raises(InvalidInstant):
        credentials.prepare_retirement(
            SimpleNamespace(path=None, original_dsn=None),
            retirement_receipt="opaque",
            retired_at=clock,
        )


def test_qualified_existing_retirement_file_is_read_without_byte_rewrite(tmp_path):
    bundle = _bundle(tmp_path)
    credentials.prepare_retirement(
        bundle, retirement_receipt="opaque", retired_at=CLOCK
    )
    payload = json.loads(bundle.path.read_bytes())
    payload["retirement"]["retired_at"] = OFFSET
    bundle.path.write_text(json.dumps(payload))
    original = bundle.path.read_bytes()
    loaded = credentials.load_bound(bundle.path)
    assert loaded.retired_at == WIRE
    assert bundle.path.read_bytes() == original


@pytest.mark.parametrize("clock", [CLOCK, OFFSET])
def test_archive_diagnostic_formats_clock_without_changing_frozen_intent(
    tmp_path, monkeypatch, clock
):
    artifact = tmp_path / "source.tar"
    artifact.write_bytes(b"opaque archive bytes")
    source = {
        "freeze_intent": {
            "receipt_id": "opaque-id",
            "frozen_at": clock,
            "database": {"org": "example"},
        }
    }
    before = deepcopy(source)
    inspection = SimpleNamespace(
        dumped_from_postgres="17",
        dumped_by_pg_dump="17",
        table_entries=2,
        archive_sha256="a" * 64,
    )
    monkeypatch.setattr(
        archive.universe_portability,
        "archive_catalog_receipt",
        lambda *args: {"opaque": True},
    )
    result = archive._archive_receipt(artifact, inspection, source)
    assert result["receipt"]["frozen_at"] == WIRE
    assert result["receipt"]["receipt_id"] == "opaque-id"
    assert source == before
    assert artifact.read_bytes() == b"opaque archive bytes"


@pytest.mark.parametrize("clock", BAD)
def test_archive_diagnostic_refuses_clock_before_filesystem_access(clock):
    with pytest.raises(InvalidInstant):
        archive._archive_receipt(None, None, {"freeze_intent": {"frozen_at": clock}})
