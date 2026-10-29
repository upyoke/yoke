"""Failure trace stays on the parent when a linked run did not fail."""

from __future__ import annotations

from yoke_core.domain.deployment_failure_trace import (
    FailedJob,
    RunSnapshot,
    github_run_ref,
    terminal_error,
    walk_failure_chain,
)


PARENT = github_run_ref("upyoke/yoke", "38619127911")
CHILD = github_run_ref("upyoke/platform", "38619420077")
JOB_URL = "https://github.com/upyoke/yoke/actions/runs/38619127911/job/116041777521"
TAG_ERROR = (
    "error (rest_transport_error): create annotated release tag failed: HTTP 504"
)
CHILD_URL = CHILD.url


def _job(ref, job_id: str, name: str, log: str, url: str = "") -> RunSnapshot:
    return RunSnapshot(ref, (FailedJob(job_id, name, log, url=url),))


def test_coded_refusal_reports_the_tag_step_and_skips_a_passing_run() -> None:
    log = "\n".join(
        [
            "2026-10-14T01:02:03.0000000Z consumer check run: upyoke/platform run 38619420077",
            "2026-10-14T01:02:04.0000000Z hosted consumer builds against this candidate: "
            f"product {'a' * 40} with consumer {'b' * 40} — {CHILD_URL}",
            f"2026-10-14T01:05:06.0000000Z {TAG_ERROR}",
            "2026-10-14T01:05:07.0000000Z ##[error]Process completed with exit code 1.",
        ]
    )
    inspected: list[str] = []

    def inspect(ref):
        inspected.append(ref.run_id)
        assert ref == PARENT
        return _job(PARENT, "116041777521", "dispatch-platform-release", log, JOB_URL)

    result = walk_failure_chain(
        PARENT,
        inspect_run=inspect,
        resolve_job=lambda _repo, _job: CHILD,
    )

    assert terminal_error(log) == TAG_ERROR
    assert result["complete"] is True
    assert result["terminal_job"] == "dispatch-platform-release"
    assert result["terminal_job_url"] == JOB_URL
    assert result["terminal_error"] == TAG_ERROR
    assert [hop["run_id"] for hop in result["chain"]] == ["38619127911"]
    assert inspected == ["38619127911"]


def test_single_url_follows_a_child_only_when_that_run_failed() -> None:
    parent_log = "\n".join(
        [
            f"see {CHILD_URL}",
            "##[error]Process completed with exit code 1.",
        ]
    )
    child_log = "##[error]registry rejected the pin"
    child_snapshot = _job(CHILD, "9", "pin check", child_log)

    def inspect(ref):
        if ref == CHILD:
            return child_snapshot
        return _job(PARENT, "1", "dispatch-platform-release", parent_log, JOB_URL)

    result = walk_failure_chain(
        PARENT,
        inspect_run=inspect,
        resolve_job=lambda _repo, _job: CHILD,
    )

    assert result["complete"] is True
    assert result["terminal_error"] == "registry rejected the pin"
    assert [hop["run_id"] for hop in result["chain"]] == [
        "38619127911",
        "38619420077",
    ]


def test_passing_child_reports_the_parent_job_and_its_last_useful_line() -> None:
    useful = "runner exited before the adapter printed a coded refusal"
    parent_log = "\n".join(
        [
            f"hosted consumer builds against this candidate — {CHILD_URL}",
            useful,
            "##[error]Process completed with exit code 1.",
        ]
    )
    inspected: list[str] = []

    def inspect(ref):
        inspected.append(ref.run_id)
        if ref == CHILD:
            return RunSnapshot(CHILD, ())
        return _job(PARENT, "1", "dispatch-platform-release", parent_log, JOB_URL)

    result = walk_failure_chain(
        PARENT,
        inspect_run=inspect,
        resolve_job=lambda _repo, _job: CHILD,
    )

    assert result["complete"] is True
    assert result["terminal_job"] == "dispatch-platform-release"
    assert result["terminal_job_url"] == JOB_URL
    assert result["terminal_error"] == useful
    assert [hop["run_id"] for hop in result["chain"]] == ["38619127911"]
    assert inspected == ["38619127911", "38619420077"]


def test_unreadable_child_conclusion_names_the_recovery() -> None:
    parent_log = "\n".join(
        [
            f"see {CHILD_URL}",
            "##[error]Process completed with exit code 1.",
        ]
    )

    def inspect(ref):
        if ref == CHILD:
            raise PermissionError("Actions logs are not visible")
        return _job(PARENT, "1", "dispatch-platform-release", parent_log, JOB_URL)

    result = walk_failure_chain(
        PARENT,
        inspect_run=inspect,
        resolve_job=lambda _repo, _job: CHILD,
    )

    assert result["complete"] is False
    assert "Actions logs are not visible" in result["stop_reason"]
    assert "restore Actions read permission" in result["recovery"]
    assert result["chain"][0]["run_id"] == "38619127911"


def test_chained_traceback_reports_the_exception_actually_raised() -> None:
    exception = "http.client.IncompleteRead: IncompleteRead(0 bytes read, 512 more expected)"
    log = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "http/client.py", line 573, in _get_chunk_left',
            "    chunk_left = self._read_next_chunk_size()",
            "ValueError: invalid literal for int() with base 16: b''",
            "",
            "During handling of the above exception, another exception occurred:",
            "",
            "Traceback (most recent call last):",
            '  File "public_health_gate.py", line 82, in read_body',
            "    response.read()",
            exception,
            "##[error]Process completed with exit code 1.",
        ]
    )
    log = "\n".join(f"2026-10-29T01:02:03.000Z {line}" for line in log.splitlines())
    result = walk_failure_chain(
        PARENT,
        inspect_run=lambda ref: _job(ref, "1", "public health", log, JOB_URL),
        resolve_job=lambda _repo, _job: CHILD,
    )

    assert terminal_error(log) == exception
    assert result["complete"] is True
    assert result["terminal_error"] == exception
