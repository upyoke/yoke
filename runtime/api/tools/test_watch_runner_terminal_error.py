"""Terminal structured errors emitted by the shared watcher runner."""

from __future__ import annotations

import io
import sys

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass


def _noise(_line: str) -> Classification:
    return Classification(LineClass.NOISE)


def _json_child(tmp_path, *, exit_code: int):
    script = tmp_path / f"json_error_{exit_code}.py"
    script.write_text(
        "import json, sys\n"
        'print(json.dumps({"ok": False, "error": '
        '"user_authorization_unavailable"}, indent=2))\n'
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return script


def _run(tmp_path, *, exit_code: int):
    raw = tmp_path / f"raw-{exit_code}.log"
    progress = tmp_path / f"progress-{exit_code}.log"
    stdout = io.StringIO()
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(_json_child(tmp_path, exit_code=exit_code))],
        classifier=_noise,
        raw_capture=raw,
        progress_capture=progress,
        kind="merge",
        stdout_stream=stdout,
    )
    return rc, raw.read_text(), progress.read_text(), stdout.getvalue()


def test_failed_watcher_restates_json_error_before_exit(tmp_path):
    rc, raw, progress, stdout = _run(tmp_path, exit_code=1)

    assert rc == 1
    terminal = "# watch_merge error: user_authorization_unavailable"
    assert terminal in progress
    assert terminal in stdout
    assert terminal not in raw
    assert progress.splitlines()[-1].startswith("# watch_merge exit=1")


def test_successful_watcher_does_not_restate_error_field(tmp_path):
    rc, _raw, progress, stdout = _run(tmp_path, exit_code=0)

    assert rc == 0
    assert "# watch_merge error:" not in progress
    assert "# watch_merge error:" not in stdout
