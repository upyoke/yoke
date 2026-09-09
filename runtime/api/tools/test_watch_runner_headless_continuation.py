"""A headless caller is told what a handed-back call still owes.

A relay-launched worker cannot be prompted again, so its turn is the whole
life of every command it starts. When the harness moves that call to a
background task, nothing about the command stops — but a caller that reads
the hand-back as completion ends the turn and kills it. The runner therefore
names the continuation as metadata before the command starts, which is the
only place a caller reading its own progress stream will find it mid-run.
"""

from __future__ import annotations

import io
import sys

from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_wait_mode import HEADLESS_CONTINUATION_DIRECTIVE
from yoke_core.tools._watch_throttle import Classification, LineClass, ThrottlePolicy


PASSTHROUGH_POLICY = ThrottlePolicy(percent_step=0.0001)


def _python_emit_script(tmp_path, lines, exit_code):
    script = tmp_path / "emit.py"
    body = [
        "import sys",
        "lines = " + repr(lines),
        "for line in lines:",
        "    print(line)",
        f"sys.exit({exit_code})",
    ]
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    return script


def _noise_classifier(_line: str) -> Classification:
    """The child's own output is irrelevant here; only metadata is asserted."""
    return Classification(LineClass.NOISE)


def test_headless_caller_is_told_to_continue_a_handed_back_call(tmp_path, monkeypatch):
    """A relay-launched turn is the whole life of the command it starts.

    The notice leads the run rather than trailing it: a harness that
    hands the call back does so mid-run, and by then the only thing
    the caller has read is what the watcher already printed.
    """
    monkeypatch.setenv(LAUNCH_CONTEXT_ENV, "{}")
    script = _python_emit_script(tmp_path, ["unrelated"], exit_code=0)
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    stdout = io.StringIO()

    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=_noise_classifier,
        raw_capture=raw,
        progress_capture=progress,
        kind="meta",
        stdout_stream=stdout,
        policy=PASSTHROUGH_POLICY,
    )

    assert rc == 0
    notice = f"# watch_meta headless_continuation: {HEADLESS_CONTINUATION_DIRECTIVE}"
    progress_lines = progress.read_text(encoding="utf-8").splitlines()
    assert progress_lines[1] == notice
    assert notice in stdout.getvalue()
    # Wrapper metadata never enters the forensic capture.
    assert "headless_continuation" not in raw.read_text(encoding="utf-8")


def test_a_caller_that_can_be_prompted_again_gets_no_notice(tmp_path, monkeypatch):
    monkeypatch.delenv(LAUNCH_CONTEXT_ENV, raising=False)
    script = _python_emit_script(tmp_path, ["unrelated"], exit_code=0)
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"

    rc = _watch_runner.run_watcher(
        argv=[sys.executable, str(script)],
        classifier=_noise_classifier,
        raw_capture=raw,
        progress_capture=progress,
        kind="meta",
        stdout_stream=io.StringIO(),
        policy=PASSTHROUGH_POLICY,
    )

    assert rc == 0
    assert "headless_continuation" not in progress.read_text(encoding="utf-8")
