"""Timing and cache-hit evidence uses native image build steps."""

import pytest
from yoke_core.tools.server_image_cache_evidence import build_seconds, postgres_cached


def _job(arch, seconds):
    return {
        "name": f"build-native-{arch}",
        "steps": [
            {
                "name": "Build and push the native content-addressed image",
                "conclusion": "success",
                "started_at": "2026-11-05T12:00:00Z",
                "completed_at": f"2026-11-05T12:00:{seconds:02d}Z",
            }
        ],
    }


def test_timing_uses_slowest_native_step_and_ignores_attestation():
    assert (
        build_seconds([_job("amd64", 25), _job("arm64", 40), {"name": "attest"}]) == 40
    )


def test_missing_architecture_cannot_pass_timing():
    with pytest.raises(ValueError, match="native_build_evidence_missing"):
        build_seconds([_job("amd64", 25)])


def test_failed_native_build_cannot_pass_timing():
    job = _job("amd64", 25)
    job["steps"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="image_build_incomplete"):
        build_seconds([job, _job("arm64", 40)])


def test_cache_hit_must_belong_to_postgres_download_step():
    step = "#12 [builder 5/12] RUN PYTHONPATH=/build/packages/yoke-core/src python -c postgres_binaries.py\n"
    assert postgres_cached(step + "#12 CACHED\n")
    assert not postgres_cached(step + "#13 CACHED\n#12 DONE 4.0s\n")
    assert not postgres_cached(
        "#12 [builder 4/12] COPY packages ./packages\n#12 CACHED\n"
    )


@pytest.mark.parametrize(
    "files, expected",
    [
        (["runtime/api/main.py"], True),
        (["packages/yoke-core/src/yoke_core/api/main.py", "docs/overview.md"], True),
        (["packages/yoke-core/src/yoke_core/domain/postgres_binaries.py"], False),
        (
            [
                "runtime/api/main.py",
                "packages/yoke-cli/src/yoke_cli/resilient_fetch.py",
            ],
            False,
        ),
        (["runtime/api/main.py", "Dockerfile"], False),
        (["docs/overview.md"], False),
    ],
)
def test_cache_reuse_proof_requires_application_change_without_bootstrap_edit(
    files, expected
):
    from yoke_core.tools.server_image_cache_evidence import (
        application_changed_without_bootstrap,
    )

    assert application_changed_without_bootstrap(files) is expected
