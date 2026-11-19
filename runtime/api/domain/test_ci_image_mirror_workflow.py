"""Mirror publication preserves architectures and proves anonymous consumption."""

from pathlib import Path

from yoke_core.domain.yaml_helper import load_document


WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/ci-image-mirror.yml"


def test_mirror_refresh_is_scheduled_manual_and_self_updating() -> None:
    workflow = load_document(WORKFLOW)
    assert workflow["on"]["schedule"] == [{"cron": "37 4 * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["push"]["paths"] == [".github/workflows/ci-image-mirror.yml"]
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "ci-image-mirror",
        "cancel-in-progress": False,
    }


def test_mirror_copies_all_consumer_images_without_cloud_credentials() -> None:
    job = load_document(WORKFLOW)["jobs"]["copy"]
    assert job["if"] == "github.repository == 'upyoke/yoke'"
    assert job["permissions"] == {"packages": "write"}
    assert job["strategy"]["fail-fast"] is False
    assert {
        (entry["image"], entry["source"])
        for entry in job["strategy"]["matrix"]["include"]
    } == {
        ("ghcr.io/upyoke/postgres:16", "docker.io/library/postgres:16"),
        ("ghcr.io/upyoke/registry:2", "docker.io/library/registry:2"),
        ("ghcr.io/upyoke/python:3.13-slim", "docker.io/library/python:3.13-slim"),
        ("ghcr.io/upyoke/buildkit:v0.34.2", "docker.io/moby/buildkit:v0.34.2"),
    }
    assert 0 < job["timeout-minutes"] <= 30
    assert all("uses" not in step for step in job["steps"])
    step = job["steps"][-1]
    assert step["env"]["REGISTRY_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    script = step["run"]
    assert "skopeo copy --all --preserve-digests --retry-times 3" in script
    assert '--src-no-creds --dest-authfile "$authfile"' in script
    assert step["env"]["SOURCE"] == "${{ matrix.source }}"
    assert 'source="docker://$SOURCE"' in script
    assert "docker://$IMAGE" in script
    assert "public.ecr.aws" not in WORKFLOW.read_text()


def test_mirror_verifies_public_digest_and_both_linux_platforms() -> None:
    script = load_document(WORKFLOW)["jobs"]["copy"]["steps"][-1]["run"]
    assert script.index("skopeo copy") < script.index("skopeo inspect --no-creds --raw")
    assert 'sha256sum "$RUNNER_TEMP/public-manifest"' in script
    assert '"$actual" != "$expected"' in script
    assert "for arch in amd64 arm64" in script
    assert '--no-creds --config "$destination"' in script
    for reason in (
        "CI-MIRROR-REFRESH",
        "CI-MIRROR-NOT-PUBLIC",
        "CI-MIRROR-DIGEST-MISMATCH",
    ):
        assert reason in script
    assert "GITHUB_STEP_SUMMARY" in script
    assert "continue-on-error" not in WORKFLOW.read_text()
