"""Published standalone kernels agree on UTC bounds and preserve old releases."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[3]
MIRROR = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree"
RELEASES = [
    (
        "structured-events",
        "5.0.0",
        "events/events_timestamps.py",
        "aa8243e5795b031015132c7875f9be227d6d76540f32554e747179499d971411",
    ),
    (
        "self-hosted-runners",
        "2.0.1",
        "infra/webapp_runner_timestamps.py",
        "f6424b143abf8873069040a8aba82e9c9e349ed3aade6cbd679d51c67ebd9266",
    ),
    (
        "webapp-scaffold",
        "1.1.4",
        "app/utils/timestamps.py",
        "2e5f513516c37faded5eca0eeb168e46295c3af8e3c32f6f335455e523c93809",
    ),
]
VALID = [
    ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000Z"),
    ("0001-01-01T05:30:00+05:30", "0001-01-01T00:00:00.000000Z"),
    ("9999-12-31T23:59:59.999999Z", "9999-12-31T23:59:59.999999Z"),
    ("9999-12-31T18:29:59.999999-05:30", "9999-12-31T23:59:59.999999Z"),
]
INVALID = ["0001-01-01T00:00:00+05:30", "9999-12-31T23:59:59.999999-05:30"]


def _latest(root, slug):
    base = root / "packs" / slug
    descriptor = json.loads((base / "pack.json").read_text())
    return base / descriptor["versions"][descriptor["latest_version"]]["source"]


@pytest.mark.parametrize("slug,previous,kernel,frozen", RELEASES)
def test_published_kernel_bytes_match_shared_contract(slug, previous, kernel, frozen):
    expected = (
        ROOT / "packages/yoke-contracts/src/yoke_contracts/timestamps.py"
    ).read_bytes()
    for root in (ROOT, MIRROR):
        assert (_latest(root, slug) / kernel).read_bytes() == expected


@pytest.mark.parametrize("slug,previous,kernel,frozen", RELEASES)
def test_published_kernel_preserves_supported_utc_boundaries(
    slug, previous, kernel, frozen
):
    for root in (ROOT, MIRROR):
        api = runpy.run_path(str(_latest(root, slug) / kernel))
        for value, wire in VALID:
            native = api["parse_instant"](value)
            assert api["format_instant"](native) == wire
            assert api["format_instant"](value) == wire
            assert native == api["parse_instant"](wire)


@pytest.mark.parametrize("slug,previous,kernel,frozen", RELEASES)
def test_published_kernel_utc_overflow_has_named_recovery(
    slug, previous, kernel, frozen
):
    for root in (ROOT, MIRROR):
        api = runpy.run_path(str(_latest(root, slug) / kernel))
        for value in INVALID:
            for supplied in (value, datetime.fromisoformat(value)):
                for function in ("parse_instant", "format_instant"):
                    with pytest.raises(api["InvalidInstant"], match="invalid_instant"):
                        api[function](supplied)


@pytest.mark.parametrize("slug,previous,kernel,frozen", RELEASES)
def test_previous_published_release_bytes_remain_frozen(slug, previous, kernel, frozen):
    for root in (ROOT, MIRROR):
        base = root / "packs" / slug
        definition = json.loads((base / "pack.json").read_text())["versions"][previous]
        source = base / definition["source"]
        roster = sorted(
            (
                entry["source"],
                hashlib.sha256((source / entry["source"]).read_bytes()).hexdigest(),
            )
            for entry in definition["files"]
        )
        digest = hashlib.sha256(
            json.dumps(roster, separators=(",", ":")).encode()
        ).hexdigest()
        assert digest == frozen
