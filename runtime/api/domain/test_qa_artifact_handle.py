"""Typed artifact-handle round-trip + validation coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.qa_artifact_handle import (
    ArtifactHandleError,
    build_artifact_key,
    handle_address,
    is_present,
    local_handle,
    parse_handle,
    s3_handle,
    serialize_handle,
)


class TestBuildArtifactKey:
    def test_key_taxonomy(self) -> None:
        key = build_artifact_key("externalwebapp", 1732, 88, "home.png")
        assert key == "qa-artifacts/externalwebapp/1732/88/home.png"

    @pytest.mark.parametrize(
        "segment", ["", "..", "a/b", "/abs", "  "],
    )
    def test_unsafe_segments_rejected(self, segment: str) -> None:
        with pytest.raises(ArtifactHandleError):
            build_artifact_key(segment, 1, 2, "f.png")
        with pytest.raises(ArtifactHandleError):
            build_artifact_key("proj", 1, 2, segment)


class TestHandleRoundTrip:
    def test_s3_handle_round_trips_through_storage_form(self) -> None:
        handle = s3_handle("p-prod-artifacts", "qa-artifacts/p/1/2/f.png",
                           content_type="image/png")
        text = serialize_handle(handle)
        parsed = parse_handle(text)
        assert parsed == handle
        assert parsed["backend"] == "s3"
        # storage form is compact + key-sorted (deterministic)
        assert text == json.dumps(handle, sort_keys=True,
                                  separators=(",", ":"))

    def test_local_handle_round_trips(self) -> None:
        handle = local_handle("/tmp/evidence/home.png")
        parsed = parse_handle(serialize_handle(handle))
        assert parsed == {"backend": "local", "path": "/tmp/evidence/home.png"}

    def test_parse_accepts_dict_payloads(self) -> None:
        parsed = parse_handle({"backend": "s3", "bucket": "b", "key": "k"})
        assert parsed["bucket"] == "b"


class TestHandleValidation:
    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "not json",
            json.dumps({"bucket": "b", "key": "k"}),  # missing backend
            json.dumps({"backend": "ftp", "path": "x"}),  # unknown backend
            json.dumps({"backend": "s3", "bucket": "b"}),  # missing key
            json.dumps({"backend": "s3", "bucket": "", "key": "k"}),
            json.dumps({"backend": "local"}),  # missing path
            json.dumps({"backend": "local", "path": "  "}),
            json.dumps(["backend", "s3"]),  # not an object
        ],
    )
    def test_malformed_payloads_raise(self, raw) -> None:
        with pytest.raises(ArtifactHandleError):
            parse_handle(raw)

    def test_bare_path_is_never_a_handle(self) -> None:
        """A bare path string must not silently become a local handle."""
        with pytest.raises(ArtifactHandleError):
            parse_handle("qa-artifacts/proj/1/2/file.png")


class TestAddressesAndPresence:
    def test_s3_address_is_object_uri(self) -> None:
        handle = s3_handle("bkt", "qa-artifacts/p/1/2/f.png")
        assert handle_address(handle) == "s3://bkt/qa-artifacts/p/1/2/f.png"

    def test_local_absolute_address_passes_through(self, tmp_path: Path) -> None:
        target = tmp_path / "f.png"
        handle = local_handle(str(target))
        assert handle_address(handle, repo_root="/elsewhere") == str(target)

    def test_local_relative_address_joins_repo_root(self) -> None:
        handle = local_handle("tests/browser/baselines/home.png")
        assert handle_address(handle, repo_root="/repo") == (
            "/repo/tests/browser/baselines/home.png"
        )

    def test_s3_handles_are_present_without_network(self) -> None:
        assert is_present(s3_handle("bkt", "k")) is True

    def test_local_presence_tracks_disk(self, tmp_path: Path) -> None:
        target = tmp_path / "shot.png"
        handle = local_handle(str(target))
        assert is_present(handle) is False
        target.write_bytes(b"PNG")
        assert is_present(handle) is True
