"""Fleet reports reach their reader while the quiet probe remains alive."""

from pathlib import Path

from yoke_core.tools import watch_tail
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
from runtime.api.tools.watch_fleet_test_harness import RecordingStream, run_probe_script


def test_a_complete_report_does_not_wait_for_another_child_write(tmp_path):
    received = tmp_path / "received"

    class Reader(RecordingStream):
        def write(self, text):
            result = super().write(text)
            if REPORT_BEGIN in text and REPORT_END in text:
                received.touch()
            return result

    out = Reader()
    code = run_probe_script(
        tmp_path,
        "import pathlib, time\n"
        f"received = pathlib.Path({str(received)!r})\n"
        f"print({(REPORT_BEGIN + chr(10) + 'current state' + chr(10) + REPORT_END)!r}, flush=True)\n"
        "deadline = time.monotonic() + 3\n"
        "while not received.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "raise SystemExit(0 if received.exists() else 1)\n",
        out,
    )
    assert code == 0
    assert len([write for write in out.writes if REPORT_BEGIN in write]) == 1


def test_tail_serves_a_report_as_one_write_and_resumes_after_it(tmp_path: Path):
    path = tmp_path / "progress.log"
    report = f"{REPORT_BEGIN}\ncurrent state\n{REPORT_END}\n"
    path.write_text(report + "# watch_fleet exit=0\n")
    first = RecordingStream()
    assert watch_tail.follow(path, out=first) == 0
    assert first.writes[0] == report
    second = RecordingStream()
    assert watch_tail.follow(path, out=second) == 0
    assert second.writes == ["# watch_fleet exit=0\n"]
