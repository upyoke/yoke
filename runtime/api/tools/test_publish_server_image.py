"""Release pointers promote exact digests without replacing immutable versions."""

import json

import pytest

from yoke_core.tools import publish_server_image as subject

VERSION = "0.2.0.202610140941"
DIGEST = "sha256:" + "a" * 64
REPO = "ghcr.io/owner/yoke-server"


def identity(monkeypatch):
    monkeypatch.setattr(
        subject,
        "validate_release_tag",
        lambda env: {
            "tag_object_sha": "b" * 40,
            "repository": REPO,
            "version_ref": f"{REPO}:{VERSION}",
            "latest_ref": f"{REPO}:latest",
        },
    )
    return {
        "EXPECTED_TAG_OBJECT_SHA": "b" * 40,
        "PUSHED_DIGEST": DIGEST,
        "GITHUB_REPOSITORY": "owner/yoke",
        "TAG_NAME": VERSION,
    }


@pytest.mark.parametrize("count", [1, 628, 1200])
def test_latest_reads_one_complete_matching_inventory(monkeypatch, count):
    calls = []
    refs = [{"ref": f"refs/tags/{VERSION}", "object": {"type": "tag"}}] * count
    monkeypatch.setattr(
        subject, "run", lambda cmd: calls.append(cmd) or json.dumps(refs)
    )
    assert subject.latest_release("owner/yoke") == VERSION
    assert calls == [["gh", "api", "repos/owner/yoke/git/matching-refs/tags/0.2.0."]]


def test_collision_does_not_publish(monkeypatch):
    env = identity(monkeypatch)
    monkeypatch.setattr(subject, "inspect", lambda ref: "sha256:" + "c" * 64)
    monkeypatch.setattr(subject, "run", lambda cmd: pytest.fail("collision published"))
    with pytest.raises(ValueError, match="release_image_collision"):
        subject.publish(env)


def test_moved_tag_does_not_publish(monkeypatch):
    env = identity(monkeypatch)
    env["EXPECTED_TAG_OBJECT_SHA"] = "c" * 40
    monkeypatch.setattr(
        subject, "inspect", lambda ref: pytest.fail("moved tag published")
    )
    with pytest.raises(ValueError, match="release_tag_moved"):
        subject.publish(env)


@pytest.mark.parametrize("latest", [VERSION, "0.2.0.202610150941"])
def test_retry_preserves_bytes_and_old_release_cannot_move_latest(monkeypatch, latest):
    env = identity(monkeypatch)
    monkeypatch.setattr(subject, "inspect", lambda ref: DIGEST)
    monkeypatch.setattr(subject, "latest_release", lambda repo: latest)
    calls = []

    def run(cmd):
        calls.append(cmd)
        return json.dumps(
            {
                "manifests": [
                    {"platform": {"os": "linux", "architecture": arch}}
                    for arch in ("amd64", "arm64")
                ]
            }
        )

    monkeypatch.setattr(subject, "run", run)
    subject.publish(env)
    publishes = [cmd for cmd in calls if "create" in cmd]
    assert len(publishes) == int(latest == VERSION)
    if publishes:
        assert f"{REPO}:latest" in publishes[0]
        assert publishes[0][-1] == f"{REPO}@{DIGEST}"
