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


def test_publication_refusal_reaches_release_failure_trace(monkeypatch, capsys):
    from yoke_core.domain.deployment_failure_trace import terminal_error

    def refuse(env):
        raise ValueError("release_image_collision: immutable version differs")

    monkeypatch.setattr(subject, "publish", refuse)
    assert subject.main() == 1
    annotation = capsys.readouterr().err.strip()
    assert annotation.startswith("::error::image_publication_refused: ")
    # GitHub Actions renders workflow error annotations in downloaded job logs.
    logged = annotation.replace("::error::", "##[error]", 1)
    diagnostic = terminal_error(logged + "\n##[error]Process completed with exit code 1.")
    assert diagnostic == (
        "image_publication_refused: release_image_collision: immutable version differs; "
        "retry the publication job after correcting the named cause"
    )


def readback(monkeypatch, reads):
    env = identity(monkeypatch)
    monkeypatch.setattr(subject, "latest_release", lambda repo: "0.2.0.202610150941")
    sequence = iter([None, *reads])
    monkeypatch.setattr(subject, "inspect", lambda ref: next(sequence))
    platforms = [{"platform": {"os": "linux", "architecture": a}} for a in ("amd64", "arm64")]
    creates = []
    monkeypatch.setattr(
        subject,
        "run",
        lambda cmd: creates.append(cmd) or json.dumps({"manifests": platforms}),
    )
    sleeps = []
    monkeypatch.setattr(subject, "sleep", sleeps.append)
    return env, creates, sleeps


def test_readback_waits_while_ghcr_does_not_yet_serve_the_new_tag(monkeypatch):
    env, creates, sleeps = readback(monkeypatch, [None, None, DIGEST])
    subject.publish(env)
    assert len([cmd for cmd in creates if "create" in cmd]) == 1
    assert sleeps == [2, 4]


def test_readback_still_missing_after_retries_refuses(monkeypatch):
    env, _, sleeps = readback(monkeypatch, [None] * 5)
    with pytest.raises(ValueError) as refused:
        subject.publish(env)
    assert sleeps == [2, 4, 8, 16]
    assert str(refused.value).startswith(
        f"published_image_mismatch: {REPO}:{VERSION} reads not found (expected {DIGEST})"
    )


def test_readback_of_a_different_digest_refuses_without_retry(monkeypatch):
    other = "sha256:" + "d" * 64
    env, _, sleeps = readback(monkeypatch, [other])
    with pytest.raises(ValueError) as refused:
        subject.publish(env)
    assert sleeps == []
    assert str(refused.value).startswith(
        f"published_image_mismatch: {REPO}:{VERSION} reads {other} (expected {DIGEST})"
    )
