"""Default bounded ``--impacted`` selection, ``--widen``, and the advisory."""

from __future__ import annotations

from yoke_core.tools import _watch_pytest_args, watch_pytest
from yoke_core.tools._impacted_selection import Selection


def _stub_binding(monkeypatch) -> None:
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
    monkeypatch.setattr(
        watch_pytest._watch_runner,
        "run_watcher",
        lambda **kwargs: 0,
    )


def _capture_bounded(monkeypatch):
    captured: dict[str, bool] = {}

    def fake_selection(base: str, *, bounded: bool = False, root=None):
        captured["base"] = base
        captured["bounded"] = bounded
        return None

    monkeypatch.setattr(watch_pytest, "_impacted_selection", fake_selection)
    return captured


def test_impacted_defaults_to_bounded(monkeypatch) -> None:
    captured = _capture_bounded(monkeypatch)
    assert watch_pytest.main(["--impacted", "main"]) == 0
    assert captured["bounded"] is True


def test_widen_disables_bounded(monkeypatch) -> None:
    captured = _capture_bounded(monkeypatch)
    assert watch_pytest.main(["--impacted", "main", "--widen"]) == 0
    assert captured["bounded"] is False


def test_bounded_flag_is_a_noop(monkeypatch) -> None:
    captured = _capture_bounded(monkeypatch)
    assert watch_pytest.main(["--impacted", "main", "--bounded"]) == 0
    assert captured["bounded"] is True


def test_widen_wins_when_both_flags_are_present(monkeypatch) -> None:
    captured = _capture_bounded(monkeypatch)
    assert watch_pytest.main(["--impacted", "main", "--bounded", "--widen"]) == 0
    assert captured["bounded"] is False


def test_widen_after_separator_is_still_a_wrapper_flag(monkeypatch) -> None:
    captured = _capture_bounded(monkeypatch)
    assert watch_pytest.main(["--impacted", "main", "--", "--widen"]) == 0
    assert captured["bounded"] is False


def test_widen_without_impacted_is_rejected(capsys) -> None:
    assert watch_pytest.main(["--widen"]) == 2
    assert _watch_pytest_args.WIDEN_WITHOUT_IMPACTED in capsys.readouterr().err


def test_bounded_without_impacted_is_rejected(capsys) -> None:
    assert watch_pytest.main(["--bounded"]) == 2
    assert _watch_pytest_args.BOUNDED_WITHOUT_IMPACTED in capsys.readouterr().err


def test_would_widen_advisory_names_rule_and_triggers(monkeypatch, capsys) -> None:
    _stub_binding(monkeypatch)
    selection = Selection(
        full_sweep=False,
        reason="selection unbounded (test_tooling_module: watch_pytest.py)",
        files=("runtime/api/tools/test_watch_pytest.py",),
        fallback_rule="test_tooling_module",
        trigger_paths=(
            "packages/yoke-core/src/yoke_core/tools/watch_pytest.py",
        ),
        bounded_deferral=True,
    )
    monkeypatch.setattr(watch_pytest, "_impacted_selection", lambda *a, **k: selection)
    assert watch_pytest.main(["--impacted", "main"]) == 0
    advisory = _watch_pytest_args.format_would_widen_advisory(
        rule="test_tooling_module",
        trigger_paths=selection.trigger_paths,
    )
    assert advisory in capsys.readouterr().out
    assert "final QA case run covers the rest" in advisory


def test_widen_does_not_print_the_advisory(monkeypatch, capsys) -> None:
    _stub_binding(monkeypatch)
    selection = Selection(
        full_sweep=True,
        reason="changed test tooling",
        fallback_rule="test_tooling_module",
        trigger_paths=(
            "packages/yoke-core/src/yoke_core/tools/watch_pytest.py",
        ),
    )
    monkeypatch.setattr(watch_pytest, "_impacted_selection", lambda *a, **k: selection)
    assert watch_pytest.main(["--impacted", "main", "--widen"]) == 0
    assert "selection would widen" not in capsys.readouterr().out
