"""Publication admits exact main-push provenance and transfers verified bytes."""

import argparse
import hashlib
import json
import zipfile

import pytest

from yoke_core.tools import promote_main_artifacts as subject


SHA = "a" * 40
VERSION = "0.2.0.202610140941"


def candidate(**changes):
    return {
        "id": 42,
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "head_repository": {"full_name": "owner/yoke"},
        "status": "completed",
        "conclusion": "success",
        **changes,
    }


def test_completed_exact_main_push_is_reused(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subject,
        "run",
        lambda cmd: (
            calls.append(cmd)
            or json.dumps(
                {
                    "workflow_runs": [
                        candidate(),
                        candidate(id=99, head_branch="topic"),
                        candidate(id=101, head_sha="b" * 40),
                        candidate(id=102, event="workflow_dispatch"),
                    ],
                }
            )
        ),
    )
    assert subject.successful_main_run("owner/yoke", "factory.yml", SHA) == 42
    assert len(calls) == 1


def test_failed_main_factory_is_not_rebuilt(monkeypatch):
    monkeypatch.setattr(
        subject,
        "run",
        lambda cmd: json.dumps({"workflow_runs": [candidate(conclusion="failure")]}),
    )
    with pytest.raises(ValueError, match="main_factory_failed"):
        subject.successful_main_run("owner/yoke", "factory.yml", SHA)


def test_missing_main_factory_times_out_with_recovery(monkeypatch):
    clock = iter([0, 301])
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(subject, "run", lambda cmd: json.dumps({"workflow_runs": []}))
    with pytest.raises(ValueError, match="main_factory_unavailable"):
        subject.successful_main_run("owner/yoke", "factory.yml", SHA)


def test_download_uses_the_proven_main_run(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subject, "successful_main_run", lambda *a: 42)
    monkeypatch.setattr(subject, "run", lambda cmd: calls.append(cmd) or "")
    assert (
        subject.download("owner/yoke", "factory.yml", SHA, "artifact", tmp_path) == 42
    )
    assert calls == [
        [
            "gh",
            "run",
            "download",
            "42",
            "--repo",
            "owner/yoke",
            "--name",
            "artifact",
            "--dir",
            str(tmp_path),
        ]
    ]


def test_oci_attestation_binds_workflow_main_sha_and_hosted_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(subject, "run", lambda cmd: calls.append(cmd) or "")
    subject.attest("oci://image@sha256:abc", "owner/yoke", SHA, "factory.yml", oci=True)
    assert calls[0][calls[0].index("--source-ref") + 1] == "refs/heads/main"
    assert calls[0][calls[0].index("--source-digest") + 1] == SHA
    assert "owner/yoke/.github/workflows/factory.yml" in calls[0]
    assert "--deny-self-hosted-runners" in calls[0]
    assert "--bundle-from-oci" in calls[0]


def image_args(tmp_path):
    return argparse.Namespace(
        kind="image",
        version=VERSION,
        source_sha=SHA,
        repo="owner/yoke",
        destination=tmp_path,
    )


@pytest.fixture
def wheel_tree(tmp_path):
    (tmp_path / "wheels").mkdir()
    records = []
    for name in ("yoke-contracts", "yoke-cli", "yoke-harness", "yoke-core"):
        path = (
            tmp_path / "wheels" / f"{name.replace('-', '_')}-{VERSION}-py3-none-any.whl"
        )
        with zipfile.ZipFile(path, "w") as out:
            out.writestr(
                f"{name}.dist-info/METADATA", f"Name: {name}\nVersion: {VERSION}\n"
            )
        body = path.read_bytes()
        records.append(
            {
                "filename": path.name,
                "name": name,
                "version": VERSION,
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    (tmp_path / "release-records.json").write_text(json.dumps(records))
    (tmp_path / "migration-history-record.json").write_text(
        json.dumps(
            {
                "artifact": {"source_commit": SHA, "engine_version": VERSION},
            }
        )
    )
    return tmp_path, records


def test_wheel_promotion_retains_exact_bytes(wheel_tree):
    root, records = wheel_tree
    before = {p.name: p.read_bytes() for p in (root / "wheels").glob("*.whl")}
    assert len(subject.validate_wheels(root, VERSION, SHA)) == 4
    assert before == {p.name: p.read_bytes() for p in (root / "wheels").glob("*.whl")}


@pytest.mark.parametrize(
    "field,value", [("version", "wrong"), ("size", 0), ("sha256", "bad")]
)
def test_corrupt_manifest_refuses(wheel_tree, field, value):
    root, records = wheel_tree
    records[0][field] = value
    (root / "release-records.json").write_text(json.dumps(records))
    with pytest.raises(ValueError, match="main_wheel_identity_mismatch"):
        subject.validate_wheels(root, VERSION, SHA)


def test_partial_wheel_tree_refuses(wheel_tree):
    root, records = wheel_tree
    (root / "release-records.json").write_text(json.dumps(records[:3]))
    with pytest.raises(ValueError, match="main_wheel_set_mismatch"):
        subject.validate_wheels(root, VERSION, SHA)


def test_image_promotion_verifies_record_and_oci_proof(monkeypatch, tmp_path):
    record = {
        "source_sha": SHA,
        "release_version": VERSION,
        "repository": "ghcr.io/owner/yoke-server",
        "digest": "sha256:" + "b" * 64,
    }
    (tmp_path / "image.json").write_text(json.dumps(record))
    downloads, attestations = [], []
    monkeypatch.setattr(subject, "download", lambda *a: downloads.append(a))
    monkeypatch.setattr(
        subject, "attest", lambda *a, **kw: attestations.append((a, kw))
    )
    assert subject.promote(image_args(tmp_path)) == record
    assert downloads[0][3] == f"yoke-image-{SHA}"
    assert attestations[0][0][0] == f"oci://{record['repository']}@{record['digest']}"


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha", "b" * 40),
        ("release_version", "0.2.0.202610140942"),
        ("repository", "ghcr.io/foreign/yoke-server"),
        ("digest", "bad"),
    ],
)
def test_mismatched_image_never_reaches_attestation(
    monkeypatch, tmp_path, field, value
):
    record = {
        "source_sha": SHA,
        "release_version": VERSION,
        "repository": "ghcr.io/owner/yoke-server",
        "digest": "sha256:" + "b" * 64,
    }
    record[field] = value
    (tmp_path / "image.json").write_text(json.dumps(record))
    monkeypatch.setattr(subject, "download", lambda *a: None)
    monkeypatch.setattr(
        subject, "attest", lambda *a, **kw: pytest.fail("invalid image was attested")
    )
    with pytest.raises(ValueError, match="main_image_identity_mismatch"):
        subject.promote(image_args(tmp_path))
