"""Release factory probes reject untrusted tags and inconsistent native images."""

import argparse
import json
import subprocess

import pytest

from yoke_core.tools import server_image_metadata as metadata
from yoke_core.tools import server_image_release_tag as tags


@pytest.fixture
def release_env():
    return {
        "TAG_NAME": "v1.2.3+launch.4",
        "GITHUB_REF": "refs/tags/v1.2.3+launch.4",
        "GITHUB_REPOSITORY": "owner/yoke",
        "GITHUB_REPOSITORY_OWNER": "Owner",
        "GITHUB_SHA": "a" * 40,
    }


def patch_tag_api(monkeypatch, *, object_type="tag", target_type="commit", source=None):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] and kwargs["timeout"] == 60
        if "/git/ref/" in command[-1]:
            obj = {"type": object_type, "sha": "b" * 40}
        else:
            obj = {"type": target_type, "sha": source or "a" * 40}
        return subprocess.CompletedProcess(command, 0, json.dumps({"object": obj}))

    monkeypatch.setattr(tags.subprocess, "run", run)
    return calls


def test_annotated_tag_outputs_exact_release_identity(monkeypatch, release_env):
    calls = patch_tag_api(monkeypatch)
    assert tags.validate_release_tag(release_env) == {
        "latest_ref": "ghcr.io/owner/yoke-server:latest",
        "repository": "ghcr.io/owner/yoke-server",
        "release_version": "1.2.3+launch.4",
        "sha_ref": "ghcr.io/owner/yoke-server:" + "a" * 12,
        "sha_tag": "a" * 12,
        "source_sha": "a" * 40,
        "tag_object_sha": "b" * 40,
    }
    assert len(calls) == 2


@pytest.mark.parametrize(
    "tag", ["v01.2.3+launch.4", "v1.2.3+launch.04", "v1.2.3", "dev"]
)
def test_noncanonical_tag_never_queries_github(monkeypatch, release_env, tag):
    calls = patch_tag_api(monkeypatch)
    release_env.update(TAG_NAME=tag, GITHUB_REF=f"refs/tags/{tag}")
    with pytest.raises(ValueError, match="without leading-zero numeric atoms"):
        tags.validate_release_tag(release_env)
    assert calls == []


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"object_type": "commit"}, "annotated tag object"),
        ({"target_type": "tag"}, "does not peel"),
        ({"source": "c" * 40}, "does not peel"),
    ],
)
def test_tag_must_peel_to_exact_workflow_commit(
    monkeypatch, release_env, overrides, reason
):
    patch_tag_api(monkeypatch, **overrides)
    with pytest.raises(ValueError, match=reason):
        tags.validate_release_tag(release_env)


@pytest.mark.parametrize(
    "arch,version,build,reason",
    [
        ("arm64", "1.2.3", "source", None),
        ("amd64", "1.2.3", "source", "architecture mismatch"),
        ("arm64", "wrong", "source", "metadata mismatch"),
        ("arm64", "1.2.3", "wrong", "metadata mismatch"),
    ],
)
def test_native_probe_exports_digest_only_after_verification(
    monkeypatch, tmp_path, arch, version, build, reason
):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] and kwargs["timeout"] == 120
        output = ""
        if command[1:3] == ["image", "inspect"]:
            output = arch + "\n"
        elif command[1] == "run":
            output = "noise\n" + metadata.format_metadata_line(
                metadata.ServerImageMetadata(version, build)
            )
        return subprocess.CompletedProcess(command, 0, output)

    monkeypatch.setattr(metadata.subprocess, "run", run)
    args = argparse.Namespace(
        image_ref="ghcr.io/owner/image@sha256:" + "d" * 64,
        expected_arch="arm64",
        expected_version="1.2.3",
        expected_build="source",
        digest_dir=tmp_path / "digests",
    )
    if reason:
        with pytest.raises(metadata.ServerImageMetadataError, match=reason):
            metadata.verify_native_image(args)
        assert not args.digest_dir.exists()
    else:
        assert "native image verified" in metadata.verify_native_image(args)
        assert list(args.digest_dir.iterdir()) == [args.digest_dir / ("d" * 64)]
        assert commands[-1][1:5] == ["run", "--rm", "--entrypoint", "python3"]
