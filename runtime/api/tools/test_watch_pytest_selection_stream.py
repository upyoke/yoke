"""Impacted-selection telemetry in minted and live pytest streams."""

from __future__ import annotations

import io
import sys

from yoke_core.tools import _watch_runner, watch_pytest
from yoke_core.tools._impacted_selection import Selection
from yoke_core.tools._watch_throttle import Classification, LineClass
from yoke_core.tools.watch_pytest_project_python import BOUNDED_DEFERRAL_VERDICT


def _bounded_selection() -> Selection:
    return Selection(
        full_sweep=False,
        reason="selection unbounded (test_tooling_module: watch_pytest.py)",
        files=("runtime/api/tools/test_watch_pytest_selection_stream.py",),
        total_files=100,
        fallback_rule="test_tooling_module",
        trigger_paths=("packages/yoke-core/src/yoke_core/tools/watch_pytest.py",),
        bounded_deferral=True,
    )


def _stub_front_door(monkeypatch) -> None:
    monkeypatch.setattr(
        watch_pytest.verification_tree_binding,
        "evaluate_run",
        lambda **_: watch_pytest.verification_tree_binding.TreeBindingVerdict(),
    )
    monkeypatch.setattr(
        watch_pytest._source_pythonpath,
        "import_origin_refusal",
        lambda *args, **kwargs: None,
    )


def test_streaming_pair_preserves_impacted_selection_flags(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    _stub_front_door(monkeypatch)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    selection = _bounded_selection()
    monkeypatch.setattr(
        watch_pytest,
        "_impacted_selection",
        lambda *args, **kwargs: selection,
    )

    assert (
        watch_pytest.main(["--print-streaming-pair", "--impacted", "main", "--bounded"])
        == 0
    )

    background = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if "yoke watch pytest" in line
    )
    assert "--impacted main --bounded" in background
    assert selection.files[0] not in background


def test_live_watcher_carries_deferral_at_start_and_finish(
    monkeypatch,
    tmp_path,
) -> None:
    _stub_front_door(monkeypatch)
    selection = _bounded_selection()
    observed: dict[str, str] = {}
    monkeypatch.setattr(
        watch_pytest,
        "_impacted_selection",
        lambda *args, **kwargs: selection,
    )

    def fake_run(**kwargs):
        kwargs["classifier"]("4 workers [7 items]")
        observed["header"] = kwargs["header_metadata"]
        observed["footer"] = kwargs["footer_metadata"]()
        return 0

    monkeypatch.setattr(watch_pytest._watch_runner, "run_watcher", fake_run)
    monkeypatch.setattr(
        watch_pytest._watch_pytest_wall_clock,
        "report",
        lambda *args, **kwargs: None,
    )

    assert watch_pytest.main(["--impacted", "main", "--bounded"]) == 0

    for rendered in observed.values():
        assert BOUNDED_DEFERRAL_VERDICT in rendered
        assert "impacted-selection scope=bounded_deferral" in rendered
        assert "rule=test_tooling_module" in rendered
        assert (
            "triggers=packages/yoke-core/src/yoke_core/tools/watch_pytest.py"
            in rendered
        )
    assert observed["footer"].endswith("items=7 of unknown")


def test_runner_writes_header_metadata_to_progress_not_raw(tmp_path) -> None:
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    stdout = io.StringIO()
    metadata = "# watch_pytest selection-start: impacted-selection scope=impacted"

    assert (
        _watch_runner.run_watcher(
            argv=[sys.executable, "-c", "print('child noise')"],
            classifier=lambda _line: Classification(LineClass.NOISE),
            raw_capture=raw,
            progress_capture=progress,
            kind="pytest",
            stdout_stream=stdout,
            header_metadata=metadata,
        )
        == 0
    )

    assert metadata in progress.read_text(encoding="utf-8")
    assert metadata in stdout.getvalue()
    assert metadata not in raw.read_text(encoding="utf-8")
