"""One-shot desktop task contract, driven by a fake scheduler; no Windows host."""

import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from yoke_contracts import windows_one_shot_task as one_shot
from yoke_contracts.windows_task_scheduler import TASK_NS

SID = "S-1-5-21-1-2-3-1001"
SIGNED_IN = (
    " USERNAME   SESSIONNAME  ID  STATE   IDLE TIME  LOGON TIME\n"
    " yokeqa     console       1  Active      none   11/23/2026 11:44 AM\n"
)


class Scheduler:
    def __init__(self, *, sessions=SIGNED_IN, statuses=("3 0",), log=b"installer said hi"):
        self.sessions, self.statuses, self.log = sessions, list(statuses), log
        self.commands, self.xml, self.wrapper = [], "", ""
        self.work = None

    def verbs(self):
        return [c[1] for c in self.commands if c[0] == "schtasks"]

    def __call__(self, argv, **_kwargs):
        self.commands.append(argv)
        out = ""
        if argv[0] == "whoami":
            out = f'"host\\yokeqa","{SID}"\n'
        elif argv[0] == "query":
            return subprocess.CompletedProcess(argv, 1, self.sessions, "")
        elif "/Create" in argv:
            document = Path(argv[argv.index("/XML") + 1])
            self.work = document.parent
            self.xml = document.read_text(encoding="utf-16")
            self.wrapper = (self.work / "run.py").read_text()
            (self.work / "output.log").write_bytes(self.log)
        elif argv[0] == "powershell.exe":
            out = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return subprocess.CompletedProcess(argv, 0, out, "")


def _run(scheduler, **kwargs):
    ticks = iter(range(0, 10_000, 100))
    return one_shot.run_one_shot(
        ["python.exe", "install.py", "--yes"],
        python="pythonw.exe",
        environment={"PATH": "C:\\uv"},
        limit_seconds=600,
        runner=scheduler,
        sleep=lambda _s: None,
        clock=lambda: next(ticks),
        **kwargs,
    )


def test_task_has_interactive_principal_no_trigger_no_restart_and_the_limit():
    root = ET.fromstring(
        one_shot.task_document(
            user_sid=SID, python="pythonw.exe", wrapper=Path("C:/w/run.py"), limit_seconds=600
        )
    )
    ns = {"t": TASK_NS}
    assert root.find("t:Principals/t:Principal/t:LogonType", ns).text == "InteractiveToken"
    assert root.find("t:Triggers", ns) is None
    assert root.find("t:Settings/t:RestartOnFailure", ns) is None
    assert root.find("t:Settings/t:ExecutionTimeLimit", ns).text == "PT600S"


def test_success_returns_exit_and_log_then_deletes_task_and_files():
    scheduler = Scheduler(statuses=("4 267009", "3 0"))
    result = _run(scheduler)
    assert (result.exit_code, result.log_tail) == (0, "installer said hi")
    assert scheduler.verbs() == ["/Create", "/Run", "/Delete"]
    assert not scheduler.work.exists()
    assert '"environment": {"PATH": "C:' in scheduler.wrapper.replace('\\"', '"')


def test_failing_command_reports_its_exit_and_still_deletes():
    scheduler = Scheduler(statuses=("3 7",))
    assert _run(scheduler).exit_code == 7
    assert scheduler.verbs()[-1] == "/Delete" and not scheduler.work.exists()


def test_not_yet_started_task_is_not_read_as_finished():
    scheduler = Scheduler(statuses=("3 267011", "4 267009", "3 0"))
    assert _run(scheduler).exit_code == 0
    assert sum(c[0] == "powershell.exe" for c in scheduler.commands) == 3


def test_timeout_ends_and_deletes_and_keeps_the_log_tail():
    scheduler = Scheduler(statuses=("4 267009",))
    with pytest.raises(one_shot.OneShotRefused, match="within 600 seconds") as caught:
        _run(scheduler)
    assert caught.value.log_tail == "installer said hi"
    assert scheduler.verbs() == ["/Create", "/Run", "/End", "/Delete"]
    assert not scheduler.work.exists()


@pytest.mark.parametrize("sessions", ["", "No User exists for *\n", " otheruser console 1 Active\n"])
def test_no_desktop_session_refuses_at_once_without_a_task(sessions):
    scheduler = Scheduler(sessions=sessions)
    with pytest.raises(one_shot.OneShotRefused, match="not signed in"):
        _run(scheduler)
    assert scheduler.verbs() == []


def test_session_row_is_read_despite_query_user_exit_one_and_current_marker():
    runner = Scheduler(sessions=">yokeqa  rdp-tcp#1  2  Aktiv  .  1/1/2026\n")
    assert one_shot.user_has_desktop_session("host\\YokeQa", runner)


def test_log_tail_prints_on_a_legacy_console_code_page():
    scheduler = Scheduler(log="\u2713 ready \ufffd".encode())
    assert _run(scheduler).log_tail.encode("cp1252") == b"? ready ?"
