"""Tests for ``yoke_core.tools.watch_doctor``.

Covers the line classifier against representative doctor output fixtures
(per-HC PASS / FAIL / WARN / SKIP, summary banners, noise), the
nested-invocation rejection path, and the passthrough-argument contract
(canonical ``-- --quick`` form, bare-form acceptance, and the help-text
worked example).
"""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.tools import watch_doctor
from yoke_core.domain.watch_runner import filter_match
from yoke_core.domain.watch_throttle import LineClass

pytestmark = pytest.mark.usefixtures("bound_project_context")


class TestDoctorClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "HC-foo: PASS",
            "HC-tier-schema-bleed: PASS",
            "HC-foo: WARN — non-fatal",
            "HC-foo: SKIP (no-op)",
            "  running HC-foo",
        ],
    )
    def test_progress_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "HC-foo: FAIL — broken",
            "HC-tier-schema-bleed: ERROR",
            "HC-something: fail",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "# Ouroboros Health Report",
            "149 checks run: 113 passed, 35 warnings, 1 failures",
            "2 checks run: 1 passed, 1 warnings, 0 failures",
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "Doctor report",
            "=== doctor finished ===",
            "10/12 checks passed",
            "Findings: 3",
        ],
    )
    def test_vestigial_summary_lines_no_longer_classify(self, line: str) -> None:
        # The old banner tokens never matched real doctor output;
        # the new regex MUST stop classifying them as SUMMARY so prose
        # drift back to the dead shapes is caught by this test.
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.NOISE

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "/tmp/sun-foo.log written",
            "",
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.NOISE


class TestUnionPattern:
    def test_progress_lines_match_union(self) -> None:
        for line in ("HC-foo: PASS", "  running HC-bar", "HC-x: WARN"):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)

    def test_urgent_lines_match_union(self) -> None:
        for line in ("HC-foo: FAIL", "HC-bar: ERROR"):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)

    def test_summary_lines_match_union(self) -> None:
        for line in (
            "# Ouroboros Health Report",
            "149 checks run: 113 passed, 35 warnings, 1 failures",
        ):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)


class TestNestedDoctorRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["yoke", "doctor", "run"],
            ["yoke", "doctor", "run", "--quick"],
            ["python3", "-m", "yoke_core.engines.doctor"],
            ["python3", "-m", "yoke_core.engines.doctor", "--quick"],
            ["python", "-m", "yoke_core.engines.doctor"],
            ["/usr/bin/python3", "-m", "yoke_core.engines.doctor"],
            ["sys.executable", "-m", "yoke_core.engines.doctor"],
        ],
    )
    def test_nested_invocation_detected(self, args: list[str]) -> None:
        assert watch_doctor._is_nested_doctor_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["--quick"],
            ["--check", "HC-foo"],
            [],
            ["python3", "-m", "pytest"],
            ["--only", "HC-doctor-run"],
        ],
    )
    def test_non_nested_invocations_pass(self, args: list[str]) -> None:
        assert not watch_doctor._is_nested_doctor_invocation(args)

    def test_rejection_message_names_both_forms(self) -> None:
        message = watch_doctor.NESTED_DOCTOR_REJECTION_MESSAGE
        assert "yoke doctor run" in message
        assert "yoke_core.engines.doctor" in message


class TestDoctorArgv:
    def test_argv_runs_the_transport_keyed_command(self) -> None:
        # The engine entrypoint opens the control-plane DB itself and
        # refuses on a relayed machine; the wrapper must run the product
        # command so it works on every transport.
        import sys

        argv = watch_doctor._doctor_argv(["--quick"])
        assert argv[0] == sys.executable
        assert argv[1:] == ["-m", "yoke_cli.main", "doctor", "run", "--quick"]
        assert "yoke_core.engines.doctor" not in argv

    def test_argv_with_no_passthrough_still_names_the_subcommand(self) -> None:
        assert watch_doctor._doctor_argv([])[1:] == [
            "-m",
            "yoke_cli.main",
            "doctor",
            "run",
        ]


class TestPassthroughParsing:
    """Bare doctor flags are forwarded; ``--`` separator works."""

    def test_canonical_separator_form_forwards(self) -> None:
        ns, passthrough = watch_doctor._parse_args(["--", "--quick"])
        assert ns.print_streaming_pair is False
        assert passthrough == ["--quick"]

    def test_bare_form_forwards(self) -> None:
        ns, passthrough = watch_doctor._parse_args(["--quick"])
        assert ns.print_streaming_pair is False
        assert passthrough == ["--quick"]

    def test_bare_and_separator_forms_produce_identical_passthrough(self) -> None:
        _, bare = watch_doctor._parse_args(["--quick"])
        _, separator = watch_doctor._parse_args(["--", "--quick"])
        assert bare == separator

    def test_wrapper_flag_still_consumed_in_bare_mix(self) -> None:
        ns, passthrough = watch_doctor._parse_args(
            ["--print-streaming-pair", "--quick"]
        )
        assert ns.print_streaming_pair is True
        assert passthrough == ["--quick"]

    def test_unrecognized_multiword_flags_forwarded(self) -> None:
        # Doctor's own arg-parser owns rejection of bogus flags; the
        # wrapper just forwards anything it does not consume.
        _, passthrough = watch_doctor._parse_args(["--check", "HC-foo"])
        assert passthrough == ["--check", "HC-foo"]

    def test_empty_argv_produces_empty_passthrough(self) -> None:
        ns, passthrough = watch_doctor._parse_args([])
        assert ns.print_streaming_pair is False
        assert passthrough == []


class TestPrintStreamingPair:
    """``--print-streaming-pair -- --quick`` emits ``-- --quick``."""

    def _capture_pair(self, argv: list[str]) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = watch_doctor.main(argv)
        assert rc == 0
        return buffer.getvalue()

    def test_streaming_pair_canonical_form(self) -> None:
        rendered = self._capture_pair(["--print-streaming-pair", "--", "--quick"])
        assert " -- --quick" in rendered
        command_anchor = f"cd {shlex.quote(os.getcwd())} && yoke watch"
        assert f"{command_anchor} doctor" in rendered
        assert f"{command_anchor} tail" in rendered
        assert "PYTHONPATH" not in rendered

    def test_streaming_pair_bare_form_normalizes_to_canonical(self) -> None:
        # The bg command in the pair is what gets pasted into Bash; it
        # must use the canonical ``-- --quick`` shape regardless of how
        # the operator invoked --print-streaming-pair.
        rendered = self._capture_pair(["--print-streaming-pair", "--quick"])
        assert " -- --quick" in rendered

    def test_streaming_pair_empty_passthrough_keeps_separator(self) -> None:
        rendered = self._capture_pair(["--print-streaming-pair"])
        # No doctor flags forwarded — but the bg command still preserves
        # the wrapper's surface so callers can append flags later.
        assert "yoke watch doctor" in rendered


def test_foreground_bash_keeps_its_existing_command_shape(monkeypatch, tmp_path):
    from yoke_core.tools import _watch_streaming_pair as renderer

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(renderer, "caller_uses_powershell", lambda: False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv(SOURCE_DEV_RUN_ROOT_ENV, raising=False)
    raw, progress = tmp_path / "raw capture", tmp_path / "progress capture"
    stream = io.StringIO()
    renderer.print_in_turn_invocation(
        kind="doctor", wrapper_module=watch_doctor.WRAPPER_MODULE,
        wrapper_args=["--quick"], raw_capture=raw, progress_capture=progress, out=stream,
    )
    assert _command_lines(stream.getvalue()) == [
        f"cd {shlex.quote(str(tmp_path.resolve()))} && yoke watch doctor "
        f"--raw-capture {shlex.quote(str(raw))} --progress-capture "
        f"{shlex.quote(str(progress))} -- --quick",
        f"tail -80 {shlex.quote(str(raw))}",
    ]


def _command_lines(output):
    return [line for line in output.splitlines() if line and not line.startswith("#")]


@pytest.mark.parametrize(
    ("ancestors", "powershell"),
    [
        (["cmd.exe", r"C:\Windows\System32\WindowsPowerShell\v1.0\PowerShell.EXE", "bash"], True),
        (["python.exe", "pwsh.exe"], True),
        (["bash.exe", "powershell.exe"], False),
        (["cmd.exe", "codex.exe"], False),
    ],
)
def test_foreground_shell_comes_from_process_ancestry(monkeypatch, ancestors, powershell):
    from yoke_core.tools import _watch_foreground_command as command

    monkeypatch.setattr(command, "os", SimpleNamespace(name="nt", getpid=os.getpid))
    monkeypatch.setattr(
        command.platform_process, "ancestors",
        lambda pid: [SimpleNamespace(name=name) for name in ancestors],
    )
    assert command.caller_uses_powershell() is powershell


@pytest.mark.windows
@pytest.mark.windows_only(reason="executes rendered commands in Windows PowerShell 5.1")
def test_foreground_powershell_runs_both_printed_lines(monkeypatch, tmp_path):
    from yoke_core.tools import _watch_streaming_pair as renderer
    from yoke_core.tools._watch_wait_mode import WatchWaitMode
    from yoke_harness.native_windows.powershell import encoded

    checkout = tmp_path / "Sam's [checkout]"
    checkout.mkdir()
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "raw = pathlib.Path(args[args.index('--raw-capture') + 1])\n"
        "raw.write_text(json.dumps([str(pathlib.Path.cwd()), args]), encoding='utf-8')\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    (tmp_path / "yoke.cmd").write_text(
        f'@"{sys.executable}" -I -S "{launcher}" %*\n', encoding="utf-8"
    )
    raw = tmp_path / "Sam's [raw capture]"
    progress = tmp_path / "Sam's [progress capture]"
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("YOKE_ENV", "selected connection")
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(checkout))
    monkeypatch.setattr(renderer, "caller_uses_powershell", lambda: True)
    monkeypatch.setattr(
        renderer, "resolve_wait_mode", lambda: WatchWaitMode("in-turn", "test caller")
    )
    monkeypatch.setattr(watch_doctor._watch_runner, "mint_capture_paths", lambda _: (raw, progress))
    monkeypatch.chdir(checkout)
    suffix = ["--quick", "", 'spaces & 100% "quoted"', "Sam’s input"]
    stream = io.StringIO()
    with redirect_stdout(stream):
        assert watch_doctor.main(["--print-streaming-pair", "--", *suffix]) == 0
    run_line, inspect_line = _command_lines(stream.getvalue())
    assert not raw.exists()
    monkeypatch.chdir(tmp_path)

    def powershell(line):
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded(line)],
            capture_output=True, text=True, timeout=30,
        )

    assert powershell(run_line).returncode == 7
    inspect = powershell(inspect_line)
    assert inspect.returncode == 0
    cwd, argv = json.loads(inspect.stdout)
    assert Path(cwd) == checkout
    assert argv == [
        "dev", "run", "--", "yoke", "--env", "selected connection", "watch", "doctor",
        "--raw-capture", str(raw), "--progress-capture", str(progress), "--", *suffix,
    ]
    raw.unlink()
    checkout.rmdir()
    refused = powershell(run_line)
    assert refused.returncode == 1
    assert "watch_checkout_entry_failed" in refused.stderr
    assert not raw.exists()
