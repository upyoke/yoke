"""Terminal-cause analysis for relayed GitHub Actions failures."""

from __future__ import annotations

from yoke_core.domain.deployment_failure_trace import (
    FailedJob,
    RunSnapshot,
    github_run_ref,
    terminal_error,
    walk_failure_chain,
)


def _snapshot(repo: str, run_id: str, job_id: str, job: str, log: str) -> RunSnapshot:
    ref = github_run_ref(repo, run_id)
    return RunSnapshot(ref, (FailedJob(job_id, job, log),))


def test_walk_reaches_registry_authentication_cause_through_job_id() -> None:
    snapshots = {
        ("upyoke/yoke", "33239728210"): _snapshot(
            "upyoke/yoke",
            "33239728210",
            "outer",
            "dispatch and await Platform release",
            "failed:failure|https://github.com/upyoke/platform/actions/runs/33239760533",
        ),
        ("upyoke/platform", "33239760533"): _snapshot(
            "upyoke/platform",
            "33239760533",
            "relay",
            "deploy-environment",
            "\n".join(
                [
                    "X engine-image / copy-attested-digest-to-ecr in 5s (ID 99067752381)",
                    "##[error]Hosted train concluded failure",
                ]
            ),
        ),
        ("upyoke/platform", "33239891656"): _snapshot(
            "upyoke/platform",
            "33239891656",
            "99067752381",
            "engine-image / copy-attested-digest-to-ecr",
            "Error response from daemon: unauthorized: authentication required",
        ),
    }

    def inspect(ref):
        return snapshots[(ref.repo, ref.run_id)]

    def resolve_job(repo: str, job_id: str):
        assert (repo, job_id) == ("upyoke/platform", "99067752381")
        return github_run_ref(repo, "33239891656")

    result = walk_failure_chain(
        github_run_ref("upyoke/yoke", "33239728210"),
        inspect_run=inspect,
        resolve_job=resolve_job,
    )

    assert result["complete"] is True
    assert result["terminal_job"] == "engine-image / copy-attested-digest-to-ecr"
    assert "unauthorized: authentication required" in result["terminal_error"]
    assert [hop["run_id"] for hop in result["chain"]] == [
        "33239728210",
        "33239760533",
        "33239891656",
    ]
    assert all(hop["url"].startswith("https://github.com/") for hop in result["chain"])


def test_walk_reaches_preflight_assertion_in_earlier_release() -> None:
    snapshots = {
        ("upyoke/yoke", "33237408825"): _snapshot(
            "upyoke/yoke",
            "33237408825",
            "outer",
            "dispatch and await Platform release",
            "failed:failure|https://github.com/upyoke/platform/actions/runs/33237604853",
        ),
        ("upyoke/platform", "33237604853"): _snapshot(
            "upyoke/platform",
            "33237604853",
            "relay",
            "deploy-environment",
            "\n".join(
                [
                    "X release route preflight in 2m22s (ID 99061579623)",
                    "##[error]Hosted train concluded failure",
                ]
            ),
        ),
        ("upyoke/platform", "33237732958"): _snapshot(
            "upyoke/platform",
            "33237732958",
            "99061579623",
            "release route preflight",
            (
                "##[error]Yoke breaks Platform: FAILED "
                "test_pinned_release_template_is_anonymously_fetchable - "
                "AssertionError: the bootstrap template is not anonymously fetchable"
            ),
        ),
    }

    result = walk_failure_chain(
        github_run_ref("upyoke/yoke", "33237408825"),
        inspect_run=lambda ref: snapshots[(ref.repo, ref.run_id)],
        resolve_job=lambda repo, job_id: github_run_ref(repo, "33237732958"),
    )

    assert result["complete"] is True
    assert result["terminal_job"] == "release route preflight"
    assert "AssertionError: the bootstrap template" in result["terminal_error"]
    assert result["chain"][-1]["run_id"] == "33237732958"


def test_terminal_error_ignores_observer_and_process_wrapper_messages() -> None:
    log = "\n".join(
        [
            "##[error]Hosted train concluded failure",
            "##[error]Process completed with exit code 1.",
        ]
    )

    assert terminal_error(log) is None


def test_unresolved_relay_returns_partial_chain_and_recovery() -> None:
    origin = github_run_ref("owner/repo", "10")
    snapshot = RunSnapshot(
        origin,
        (FailedJob("20", "await child", "Hosted train concluded failure"),),
    )

    result = walk_failure_chain(
        origin,
        inspect_run=lambda _ref: snapshot,
        resolve_job=lambda _repo, _job: github_run_ref("owner/repo", "99"),
    )

    assert result["complete"] is False
    assert result["chain"][0]["url"] == origin.url
    assert "did not resolve its downstream run" in result["stop_reason"]
    assert result["recovery"]


def test_unrecognized_terminal_shape_does_not_degrade_to_success() -> None:
    origin = github_run_ref("owner/repo", "10")
    snapshot = RunSnapshot(origin, (FailedJob("20", "build", "failure"),))

    result = walk_failure_chain(
        origin,
        inspect_run=lambda _ref: snapshot,
        resolve_job=lambda _repo, _job: origin,
    )

    assert result["complete"] is False
    assert "cause could not be read" in result["stop_reason"]


def test_permission_refusal_preserves_the_unreadable_hop_url() -> None:
    origin = github_run_ref("owner/repo", "10")

    def inspect(_ref):
        raise PermissionError("Actions logs are not visible")

    result = walk_failure_chain(
        origin,
        inspect_run=inspect,
        resolve_job=lambda _repo, _job: origin,
    )

    assert result["complete"] is False
    assert result["chain"] == [
        {
            "repo": "owner/repo",
            "run_id": "10",
            "url": origin.url,
            "failed_job": "",
        }
    ]
    assert "Actions logs are not visible" in result["stop_reason"]
    assert "restore Actions read/log permission" in result["recovery"]
