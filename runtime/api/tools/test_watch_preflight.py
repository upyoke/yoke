"""Fleet-preflight watcher classification and end-to-end capture behavior."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.tools import watch_preflight, watch_tail
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("engine artifact: wheel yoke_core.whl sha256:abc", LineClass.PROGRESS),
        ("COPY/CONVERGE yoke_alpha: starting rehearsal", LineClass.PROGRESS),
        ("converging yoke_alpha", LineClass.PROGRESS),
        ("PASS yoke_alpha: 0007_x -> converged", LineClass.SUMMARY),
        ("FAIL yoke_beta: could not copy: pg_dump failed", LineClass.URGENT),
        ("1 passed, 1 failed", LineClass.SUMMARY),
        ("receipt recorded on prod covering 7 history entries", LineClass.SUMMARY),
        ("unrelated child detail", LineClass.NOISE),
    ],
)
def test_preflight_signal_classes(line: str, expected: LineClass) -> None:
    assert watch_preflight.classify_preflight_line(line).cls == expected


def test_union_pattern_matches_every_signal_shape() -> None:
    for line in (
        "engine artifact: wheel yoke_core.whl sha256:abc",
        "COPY/CONVERGE yoke_alpha: starting rehearsal",
        "converging yoke_alpha",
        "PASS yoke_alpha: nothing pending -> converged",
        "FAIL yoke_beta: could not read ownership",
        "1 passed, 1 failed",
        "receipt recorded on prod covering 7 history entries",
    ):
        assert watch_preflight.PREFLIGHT_PROGRESS_PATTERN.search(line), line


def test_wrapper_is_registered_under_the_preflight_cli_form() -> None:
    assert WRAPPER_MAINS[watch_preflight.WRAPPER_MODULE] is watch_preflight.main
    assert WATCH_CLI_TOKENS[watch_preflight.WRAPPER_MODULE] == (
        "watch",
        "preflight",
    )
    assert cli_form(watch_preflight.WRAPPER_MODULE) == "yoke watch preflight"


def test_help_epilog_teaches_read_then_converge_or_remove() -> None:
    epilog = watch_preflight.HELP_EPILOG
    assert "capability-settings get" in epilog
    assert "capability-settings set --base <as-read>" in epilog
    assert "capability-settings remove --base <as-read>" in epilog
    assert "Never guess an enum value or hand-edit SQL" in epilog


def test_help_epilog_teaches_per_environment_receipts() -> None:
    epilog = watch_preflight.HELP_EPILOG
    assert "positional names the fleet to rehearse" in epilog
    assert "--receipt-env" in epilog
    assert "one environment's receipt never satisfies another" in epilog
    assert "<admin-connection-for-one-env>" in epilog
    assert "<admin-connection-for-another-env>" in epilog
    assert "--receipt-env <control-plane>" in epilog
    assert "yoke watch preflight -- stage --record-receipt" in epilog
    assert "Ordinary pre-release rehearsal uses the source tree" in epilog
    assert epilog.index(
        "yoke watch preflight -- stage --record-receipt"
    ) < epilog.index("--engine-wheel /path/to/yoke_core-release.whl")


def test_streaming_pair_uses_the_registered_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    monkeypatch.setattr(
        watch_preflight._watch_runner,
        "mint_capture_paths",
        lambda _kind: (raw, progress),
    )

    assert watch_preflight.main(["--print-streaming-pair", "--", "prod-db-admin"]) == 0

    output = capsys.readouterr().out
    assert "yoke watch preflight --raw-capture" in output
    assert "-- prod-db-admin" in output
    assert f"yoke watch tail {progress}" in output


def test_fake_preflight_streams_stops_tail_and_propagates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = tmp_path / "fake_preflight.py"
    child.write_text(
        "import os\n"
        "print('COPY/CONVERGE yoke_alpha: starting rehearsal')\n"
        "print('converging yoke_alpha')\n"
        "print('PASS yoke_alpha: 0007_x -> converged')\n"
        "print('FAIL yoke_beta: could not copy: pg_dump failed')\n"
        "print('1 passed, 1 failed')\n"
        "print('unbuffered=' + os.environ.get('PYTHONUNBUFFERED', ''))\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    monkeypatch.setattr(
        watch_preflight,
        "_preflight_argv",
        lambda _args: [sys.executable, str(child)],
    )

    rc = watch_preflight.main(
        [
            "--raw-capture",
            str(raw),
            "--progress-capture",
            str(progress),
            "--",
            "prod-db-admin",
        ]
    )

    assert rc == 7
    streamed = capsys.readouterr().out
    assert "COPY/CONVERGE yoke_alpha" in streamed
    assert "PASS yoke_alpha" in streamed
    assert "FAIL yoke_beta" in streamed
    assert "# watch_preflight exit=7" in streamed
    assert "unbuffered=1" in raw.read_text(encoding="utf-8")

    followed = io.StringIO()
    assert watch_tail.follow(progress, out=followed, poll_interval=0) == 0
    assert "# watch_preflight exit=7" in followed.getvalue()
