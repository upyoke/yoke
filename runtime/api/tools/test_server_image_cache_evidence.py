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
    mounted = "#7 [runtime-base 6/6] RUN --mount=type=bind,source=x,target=/bootstrap PYTHONPATH=/bootstrap python -c postgres_binaries.py\n"
    assert postgres_cached(mounted + "#7 CACHED\n")
    assert not postgres_cached(mounted + "#8 CACHED\n#7 DONE 3s\n")
    assert not postgres_cached(step + "#13 CACHED\n#12 DONE 4.0s\n")
    assert not postgres_cached(
        "#12 [builder 4/12] COPY packages ./packages\n#12 CACHED\n"
    )


def test_transfer_diagnostics_keep_parallel_vertex_times_without_changing_build_metric():
    from yoke_core.tools.server_image_cache_evidence import buildkit_timings

    log = (
        "2026-11-05T12:00:00Z #5 exporting to GitHub Actions Cache\n"
        "#6 exporting to image\n#6 exporting layers 3.0s done\n"
        "#5 preparing build cache for export\n#5 DONE 45.2s\n#6 DONE 12.1s\n"
        "#7 [builder 5/12] RUN postgres_binaries.py\n#7 CACHED\n"
    )
    assert buildkit_timings(log) == [
        {"step": "exporting to GitHub Actions Cache", "seconds": 45.2},
        {"step": "exporting to image", "seconds": 12.1},
    ]
    assert build_seconds([_job("amd64", 25), _job("arm64", 40)]) == 40


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


@pytest.mark.parametrize(
    "cached_seconds, samples, legacy, expected",
    [
        (10, 10, False, 0),
        (11, 10, False, 1),
        (10, 9, False, 1),
        (10, 10, True, 1),
        (10, 10, "registry-max", 1),
    ],
)
def test_command_uses_authenticated_rest_and_requires_ten_runs_and_thirty_seconds(
    monkeypatch, cached_seconds, samples, legacy, expected, capsys
):
    import base64
    from yoke_core.tools import server_image_cache_evidence as evidence

    monkeypatch.setattr(evidence, "github_token", lambda repository: "fixture-token")
    monkeypatch.setattr(
        "sys.argv",
        ["evidence", "--repository", "owner/repo"]
        + [
            argument
            for run_id in range(100, 110)
            for argument in ("--baseline-run", str(run_id))
        ],
    )

    def rest(path, *, query=None, token):
        assert token == "fixture-token"
        if path.endswith("/runs"):
            return {
                "workflow_runs": [
                    {
                        "id": i,
                        "head_sha": f"source-{i}",
                        "html_url": f"https://example.test/{i}",
                    }
                    for i in range(samples)
                ]
            }
        if "/contents/" in path:
            return {
                "content": base64.b64encode(
                    b"cache-to: type=gha,mode=max,scope=yoke-server-linux/amd64"
                    if legacy is True
                    else b"cache-to: type=registry,ref=${{ needs.validate-tag.outputs.repository }}:buildcache-${{ matrix.arch }},mode=min".replace(
                        b"mode=min", b"mode=max"
                    )
                    if legacy == "registry-max"
                    else b"cache-to: type=registry,ref=${{ needs.validate-tag.outputs.repository }}:buildcache-${{ matrix.arch }},mode=min"
                ).decode()
            }
        if "/compare/" in path:
            return {"files": [{"filename": "runtime/api/server.py"}]}
        assert path.endswith("/jobs")
        seconds = 40 if int(path.split("/")[-2]) >= 100 else cached_seconds
        return {
            "jobs": [dict(_job(arch, seconds), id=arch) for arch in ("amd64", "arm64")]
        }

    monkeypatch.setattr(evidence, "rest_get", rest)
    monkeypatch.setattr(
        evidence,
        "fetch_job_log",
        lambda *args, **kwargs: (
            "#12 [builder 5/12] RUN PYTHONPATH=/build/src postgres_binaries.py\n#12 CACHED\n"
        ),
    )
    assert evidence.main() == expected
    assert "fixture-token" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "stdout, code, allowed",
    [
        ("username=x-access-token\npassword=fixture-token\n", 0, True),
        ("", 0, False),
        ("password=fixture-token\n", 1, False),
    ],
)
def test_git_helper_output_stays_private_and_auth_failure_names_repair(
    monkeypatch, stdout, code, allowed, capsys
):
    from types import SimpleNamespace
    from yoke_core.tools import server_image_cache_evidence as evidence

    def run(command, **kwargs):
        assert command == ["git", "credential", "fill"]
        assert kwargs["capture_output"] is True
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert "path=owner/repo" in kwargs["input"]
        return SimpleNamespace(stdout=stdout, returncode=code)

    monkeypatch.setattr(evidence.subprocess, "run", run)
    if allowed:
        assert evidence.github_token("owner/repo") == "fixture-token"
    else:
        with pytest.raises(ValueError, match="github_read_auth_unavailable"):
            evidence.github_token("owner/repo")
    assert "fixture-token" not in capsys.readouterr().out
