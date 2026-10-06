"""GitHub Actions job logs in the exact shape the job-logs endpoint serves.

Every line carries GitHub's leading ISO timestamp; steps open with
``##[group]Run``; a failing step ends at its ``##[error]`` annotation;
``if: always()`` upload steps and post-job cleanup follow the failure.
These are the regions a failed-job report must see past.
"""

from __future__ import annotations

from typing import List

FIRST_ASSERTION = "E       AssertionError: assert 'teardown' == 'failure region'"
SUMMARY_LINE = (
    "FAILED runtime/api/domain/test_region.py::TestRegion::test_case_0 - "
    "AssertionError: assert 'teardown' == 'failure region'"
)
TYPE_ERROR = "src/app.ts(12,5): error TS2304: Cannot find name 'missingSymbol'."


def _stamp(lines: List[str]) -> str:
    return (
        "\n".join(
            f"2026-10-05T18:{index // 60 % 60:02d}:{index % 60:02d}.1234567Z {line}"
            for index, line in enumerate(lines)
        )
        + "\n"
    )


def _checkout() -> List[str]:
    return [
        "##[group]Run actions/checkout@v4",
        "with:",
        "  repository: o/r",
        "##[endgroup]",
        "Syncing repository: o/r",
    ]


def _upload_and_cleanup(upload_lines: int) -> List[str]:
    return [
        "##[group]Run actions/upload-artifact@v4",
        "with:",
        "  name: pytest-report",
        "##[endgroup]",
        *(f"Uploaded bytes {index * 4096}" for index in range(upload_lines)),
        "Artifact pytest-report has been successfully uploaded!",
        "Post job cleanup.",
        "[command]/usr/bin/git version",
        "Cleaning up orphan processes",
    ]


def pytest_job_log(
    *,
    progress_lines: int = 400,
    failures: int = 1,
    traceback_lines: int = 12,
    upload_lines: int = 80,
) -> str:
    """A pytest shard that failed *failures* tests, then uploaded its report."""
    body: List[str] = [
        *_checkout(),
        "##[group]Run python3 -m yoke_core.tools.run_tests -n auto",
        "python3 -m yoke_core.tools.run_tests -n auto",
        "shell: /usr/bin/bash -e {0}",
        "##[endgroup]",
        *(
            f"runtime/api/domain/test_mod_{index}.py ........ [{index % 100:3d}%]"
            for index in range(progress_lines)
        ),
        "\x1b[31m=================================== FAILURES ===================================\x1b[0m",
    ]
    for case in range(failures):
        body.append(
            f"___________________ TestRegion.test_case_{case} ___________________"
        )
        body.extend(f"    frame {case}.{line}" for line in range(traceback_lines))
        body.append(
            FIRST_ASSERTION if case == 0 else f"E       AssertionError: case {case}"
        )
    body.append(
        "=========================== short test summary info ============================"
    )
    body.append(SUMMARY_LINE)
    body.extend(
        f"FAILED runtime/api/domain/test_region.py::TestRegion::test_case_{case} - AssertionError"
        for case in range(1, failures)
    )
    body.append(
        f"================= {failures} failed, 4123 passed in 312.45s ================="
    )
    body.append("##[error]Process completed with exit code 1.")
    body.extend(_upload_and_cleanup(upload_lines))
    return _stamp(body)


def build_job_log(*, build_lines: int = 300, upload_lines: int = 40) -> str:
    """A compile step that failed with no pytest output."""
    return _stamp(
        [
            *_checkout(),
            "##[group]Run npm ci",
            *(f"added package {index}" for index in range(40)),
            "##[endgroup]",
            "##[group]Run npm run build",
            "npm run build",
            "##[endgroup]",
            *(f"compiling module {index}" for index in range(build_lines)),
            TYPE_ERROR,
            "##[error]Process completed with exit code 2.",
            *_upload_and_cleanup(upload_lines),
        ]
    )


__all__ = [
    "FIRST_ASSERTION",
    "SUMMARY_LINE",
    "TYPE_ERROR",
    "build_job_log",
    "pytest_job_log",
]
