"""Tests for proving the installed Yoke build against its published release."""

from __future__ import annotations

import json

import pytest

from yoke_cli.config import release_build
from yoke_cli.self_host import release_target

VERSION = "0.2.0.202610192204"
BASE = "https://distribution.example"
COMMIT = "e2ec8be23286fbc918a6375dc2717c3d612dc87c"
RELEASE = f"{BASE}/dist/releases/{VERSION}"
RECORDS = [
    {"filename": f"yoke_cli-{VERSION}-py3-none-any.whl", "sha256": "a" * 64},
    {"filename": f"yoke_core-{VERSION}-py3-none-any.whl", "sha256": "b" * 64},
]


def _serve(monkeypatch, *, published=COMMIT, records=RECORDS, missing=()):
    documents = {
        f"{RELEASE}/migration-history.json": {
            "artifact": {"engine_version": VERSION, "source_commit": published}
        },
        f"{RELEASE}/release-records.json": records,
    }

    def fetch(url: str) -> bytes:
        if url in missing or url not in documents:
            raise release_target.ReleaseTargetError(f"could not fetch {url}: 404")
        return json.dumps(documents[url]).encode()

    monkeypatch.setattr(release_target, "_FETCH_BYTES", fetch)


def _verify(source_commit=COMMIT):
    return release_build.verify_installed(
        version=VERSION, source_commit=source_commit, base_url=BASE
    )


def test_matching_commit_returns_the_published_wheel_hashes(monkeypatch):
    _serve(monkeypatch)
    assert _verify() == RECORDS


def test_mismatched_commit_refuses_and_names_both_commits(monkeypatch):
    _serve(monkeypatch, published="f" * 40)
    with pytest.raises(release_build.ReleaseBuildError) as raised:
        _verify()
    message = str(raised.value)
    assert message.startswith("installed_build_mismatch:")
    assert COMMIT in message and "f" * 40 in message
    assert f"YOKE_INSTALL_BASE_URL={BASE} sh -s -- --version {VERSION}" in message


def test_manifest_without_a_commit_refuses_as_a_mismatch(monkeypatch):
    _serve(monkeypatch, published="")
    with pytest.raises(release_build.ReleaseBuildError, match="<missing>"):
        _verify()


def test_installed_wheel_without_a_commit_refuses_before_fetching(monkeypatch):
    monkeypatch.setattr(
        release_target, "_FETCH_BYTES", lambda _url: pytest.fail("network")
    )
    with pytest.raises(
        release_build.ReleaseBuildError, match="installed_source_commit_unavailable"
    ):
        _verify(source_commit="")


def test_unpublished_release_records_refuse_with_the_origin(monkeypatch):
    _serve(monkeypatch, missing=(f"{RELEASE}/release-records.json",))
    with pytest.raises(release_build.ReleaseBuildError) as raised:
        _verify()
    assert str(raised.value).startswith("release_record_unavailable:")
    assert "yoke settings get distribution" in str(raised.value)


def test_release_records_must_be_a_list(monkeypatch):
    _serve(monkeypatch, records={"filename": "x"})
    with pytest.raises(release_build.ReleaseBuildError, match="not a JSON list"):
        _verify()


def test_a_wheel_record_without_a_hash_refuses(monkeypatch):
    _serve(monkeypatch, records=[{"filename": "yoke_cli.whl"}])
    with pytest.raises(release_build.ReleaseBuildError, match="filename and sha256"):
        _verify()
