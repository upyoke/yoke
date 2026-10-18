"""Only the main native Chromium process receives graceful shutdown."""

from pathlib import Path

from yoke_harness import linux_desktop_chromium as host
from yoke_harness import linux_chromium_processes as processes


def test_proc_selection_handles_flattened_titles_and_excludes_crashpad(
    tmp_path, monkeypatch
):
    programs = {
        101: ("chrome", b"/snap/chromium/chrome --remote-debugging-port=0\0"),
        102: ("chrome", b"/snap/chromium/chrome --type=renderer --other\0"),
        103: ("chrome", b"/snap/chromium/chrome\0--type=zygote\0"),
        104: ("chrome_crashpad_handler", b"chrome_crashpad_handler\0--monitor-self\0"),
        105: ("chromium", b"chromium\0--user-data-dir=/fixture\0"),
        106: ("unrelated", b"unrelated --name=chromium\0"),
    }
    for pid, (_, command) in programs.items():
        process = tmp_path / str(pid)
        process.mkdir()
        (process / "cmdline").write_bytes(command)
    real_path = Path
    monkeypatch.setattr(
        processes,
        "Path",
        lambda value: tmp_path if str(value) == "/proc" else real_path(value),
    )
    monkeypatch.setattr(
        host.os,
        "readlink",
        lambda path: "/snap/chromium/3560/" + programs[int(path.parent.name)][0],
    )
    assert set(host.browser_pids()) == {101, 105}


def test_quit_signals_only_selected_main_and_waits(monkeypatch):
    states = iter([[101], [101], []])
    monkeypatch.setattr(host, "browser_pids", lambda: next(states))
    signals = []
    monkeypatch.setattr(host.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(host.time, "sleep", lambda delay: None)
    assert host.quit_chromium()
    assert signals == [(101, host.signal.SIGTERM)]
