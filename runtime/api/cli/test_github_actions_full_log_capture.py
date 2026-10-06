"""``yoke github-actions failed-log --full`` writes complete logs locally.

The complete log downloads from the signed address the server returns,
so it is never truncated and never travels in the bounded response.
"""

from __future__ import annotations

import io
import json
import tempfile
import urllib.error
from pathlib import Path
from typing import Any, Dict, List

import pytest

from runtime.api.cli.test_yoke_operations_cli_github_actions_failed_log import (
    _CAPTURED_REQUESTS,
    _run,
)
from runtime.api.domain.github_actions_job_log_samples import pytest_job_log
from yoke_cli.commands.adapters import github_actions_full_log_capture as capture


SIGNED = "https://results.example/{job_id}.txt?sig=abc"


@pytest.fixture(autouse=True)
def _captures_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def _job(job_id: str, name: str, *, url: str | None = None) -> Dict[str, Any]:
    return {
        "job_id": job_id,
        "name": name,
        "html_url": f"https://github.com/o/r/actions/runs/1/job/{job_id}",
        "log_download_url": SIGNED.format(job_id=job_id) if url is None else url,
        "log_download_detail": "",
    }


class _Body(io.BytesIO):
    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _serve(monkeypatch: pytest.MonkeyPatch, bodies: Dict[str, Any]) -> List[str]:
    opened: List[str] = []

    def _fake(url: str, timeout: float) -> _Body:
        opened.append(url)
        body = bodies[url]
        if isinstance(body, Exception):
            raise body
        return _Body(body)

    monkeypatch.setattr(capture, "urlopen", _fake)
    return opened


def _full_run(*extra: str, jobs: List[Dict[str, Any]]) -> tuple[int, str, str]:
    return _run(
        "github-actions",
        "failed-log",
        "o/r",
        "1",
        "--project",
        "p",
        "--full",
        *extra,
        result={"run_id": "1", "output": "region report", "jobs": jobs},
    )


def test_full_writes_every_complete_log_untruncated(monkeypatch) -> None:
    complete = pytest_job_log(progress_lines=20_000).encode()
    _serve(
        monkeypatch,
        {
            SIGNED.format(job_id="901"): complete,
            SIGNED.format(job_id="902"): b"short\n",
        },
    )

    rc, out, err = _full_run(jobs=[_job("901", "shard (3.13, 1)"), _job("902", "lint")])

    assert rc == 0, err
    assert _CAPTURED_REQUESTS[-1].payload["full"] is True
    assert out.startswith("region report\n")
    paths = [
        line.split(": ", 1)[1].rsplit(" (", 1)[0]
        for line in out.splitlines()
        if " · " in line
    ]
    assert len(paths) == 2
    assert Path(paths[0]).read_bytes() == complete
    assert Path(paths[0]).name == "job-901-shard-3.13-1.log"
    assert Path(paths[1]).read_bytes() == b"short\n"


def test_expired_link_is_named_and_fails_the_command(monkeypatch) -> None:
    url = SIGNED.format(job_id="901")
    expired = urllib.error.HTTPError(url, 403, "expired", {}, io.BytesIO(b""))
    _serve(monkeypatch, {url: expired})

    rc, out, _err = _full_run(jobs=[_job("901", "shard")])

    assert rc == 1
    assert "not written — GitHub refused the download (HTTP 403)" in out
    assert "re-run with --full" in out
    assert "https://github.com/o/r/actions/runs/1/job/901" in out


def test_server_reason_without_link_is_reported(monkeypatch) -> None:
    _serve(monkeypatch, {})
    job = _job("901", "shard", url="")
    job["log_download_detail"] = "GitHub holds no log for this job"

    rc, out, _err = _full_run(jobs=[job])

    assert rc == 1
    assert "GitHub holds no log for this job" in out


def test_json_mode_carries_the_written_paths(monkeypatch) -> None:
    _serve(monkeypatch, {SIGNED.format(job_id="901"): b"log\n"})

    rc, out, _err = _full_run("--json", jobs=[_job("901", "shard")])

    assert rc == 0
    [written] = json.loads(out)["result"]["full_logs"]
    assert Path(written["path"]).read_bytes() == b"log\n"
    assert written["byte_count"] == 4


def test_server_without_full_capture_is_refused_by_name(monkeypatch) -> None:
    _serve(monkeypatch, {})
    old_server_job = {"job_id": "901", "name": "shard", "html_url": ""}

    rc, out, err = _full_run(jobs=[old_server_job])

    assert rc == 1
    assert "region report" in out
    assert "full_log_capture_unsupported" in err


def test_plain_http_link_is_never_downloaded(monkeypatch) -> None:
    opened = _serve(monkeypatch, {})

    rc, out, _err = _full_run(jobs=[_job("901", "shard", url="http://x.test/l")])

    assert rc == 1
    assert opened == []
    assert "not HTTPS" in out
