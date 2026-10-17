"""Routine watcher progress never wakes a follower on its own.

A release's deploy watcher batched its timing lines into a digest every
two minutes, and each digest was a wake, so steering filtered its tail
with ``grep -v '^# watch_deploy digest'``. Every kind's digests and stall
notices now stay in the progress capture and reach the reader in front of
the next line that does wake it: a failure, refusal, decision-needing
wait, terminal outcome or the exit sentinel.
"""

from __future__ import annotations

import io
from pathlib import Path

from yoke_core.tools import watch_tail
from yoke_core.tools._watch_capture_binding import writer_marker_line
from yoke_core.tools._watch_digest import ROUTINE_PROGRESS_RE

DIGEST = (
    '# watch_deploy digest: Deployment start timing: {"step": '
    '"release_start_schema", "seconds": 4.2}\n'
)
STALL = "# watch_qa_plan still running; waiting on: child process; no child output for 300s\n"


class _Writes(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        self.writes.append(text)
        return super().write(text)


def _follow(tmp_path: Path, *lines: str) -> list[str]:
    progress = tmp_path / "progress.log"
    progress.write_text(writer_marker_line("deploy") + "".join(lines), encoding="utf-8")
    out = _Writes()
    assert watch_tail.follow(progress, out=out, poll_interval=0.01) == 0
    return out.writes


def test_routine_lines_of_every_kind_are_recognised() -> None:
    for line in (DIGEST, STALL, writer_marker_line("merge")):
        assert ROUTINE_PROGRESS_RE.match(line)
    for line in (
        "# watch_deploy exit=0 raw=/tmp/raw.log\n",
        "# watch_pytest summary: 3 failed\n",
        "# watch_deploy failure: stage hosted-release failed\n",
        "ERROR: deployment refused\n",
    ):
        assert not ROUTINE_PROGRESS_RE.match(line)


def test_digests_and_stall_notices_ride_the_next_wake(tmp_path: Path) -> None:
    writes = _follow(
        tmp_path,
        DIGEST,
        STALL,
        DIGEST,
        "ERROR: stage approval refused\n",
        "# watch_deploy exit=1 raw=/tmp/raw.log\n",
    )

    assert len(writes) == 2
    assert writes[0].endswith("ERROR: stage approval refused\n")
    assert writes[0].count("# watch_deploy digest") == 2
    assert STALL in writes[0]
    assert writes[1] == "# watch_deploy exit=1 raw=/tmp/raw.log\n"


def test_a_quiet_run_wakes_only_at_its_sentinel(tmp_path: Path) -> None:
    writes = _follow(
        tmp_path, DIGEST, DIGEST, "# watch_deploy exit=0 raw=/tmp/raw.log\n"
    )

    assert len(writes) == 1
    assert writes[0].endswith("# watch_deploy exit=0 raw=/tmp/raw.log\n")
    assert writes[0].count("# watch_deploy digest") == 2
