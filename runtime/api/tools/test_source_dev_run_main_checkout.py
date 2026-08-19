"""Mapped-main fallback coverage for ``yoke dev run``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from yoke_core.domain.verification_tree_binding import ClaimLookup
from yoke_core.tools import source_dev_run


def _make_source_checkout(path: Path) -> Path:
    (path / "packages/yoke-core/src/yoke_core").mkdir(parents=True)
    (path / "pyproject.toml").touch()
    return path.resolve()


def _set_zero_live_claims(monkeypatch) -> None:
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "ambient_session_id",
        lambda: "session-1",
    )
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _session_id: ClaimLookup(worktrees=(), reachable=True),
    )


def test_zero_live_claims_select_the_mapped_main_checkout(monkeypatch, tmp_path):
    main = _make_source_checkout(tmp_path / "main")
    _set_zero_live_claims(monkeypatch)
    monkeypatch.setattr(
        source_dev_run,
        "_mapped_main_source_root",
        lambda: (main, None, 17),
    )

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert (root, error, fallback_project_id) == (main, None, 17)


def test_mapping_requires_an_existing_yoke_shaped_checkout(
    monkeypatch,
    tmp_path,
):
    plain = tmp_path / "plain"
    plain.mkdir()
    mappings = [
        SimpleNamespace(checkout=plain, project_id=17),
        SimpleNamespace(checkout=tmp_path / "missing", project_id=18),
    ]
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.configured_projects",
        lambda **_kwargs: mappings,
    )

    root, error, project_id = source_dev_run._mapped_main_source_root()

    assert root is None
    assert project_id is None
    assert "no existing Yoke-shaped source checkout" in error


def test_mapping_refuses_multiple_yoke_source_checkouts(monkeypatch, tmp_path):
    first = _make_source_checkout(tmp_path / "first")
    second = _make_source_checkout(tmp_path / "second")
    mappings = [
        SimpleNamespace(checkout=first, project_id=17),
        SimpleNamespace(checkout=second, project_id=18),
    ]
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.configured_projects",
        lambda **_kwargs: mappings,
    )

    root, error, project_id = source_dev_run._mapped_main_source_root()

    assert root is None
    assert project_id is None
    assert "multiple Yoke source checkouts" in error
    assert str(first) in error
    assert str(second) in error


def test_fallback_event_names_the_main_tree_without_copying_arguments(
    monkeypatch,
    tmp_path,
):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            success=True,
            result={"emitted": True, "event_id": "event-1", "reason": ""},
            error=None,
        )

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        _dispatch,
    )

    error = source_dev_run._record_main_checkout_fallback(
        session_id="session-1",
        root=tmp_path,
        project_id=17,
        command=["python3", "-c", "secret value"],
    )

    assert error is None
    payload = captured["payload"]
    assert payload["name"] == source_dev_run.MAIN_CHECKOUT_FALLBACK_EVENT
    assert payload["project"] == "17"
    assert payload["context"] == {
        "checkout": str(tmp_path),
        "command_name": "python3",
        "argument_count": 2,
        "fallback_reason": "no_live_claimed_yoke_source_lane",
        "read_only_intent": True,
        "write_target_if_child_writes": "main",
    }
    assert "secret value" not in repr(payload)
    assert captured["actor"].session_id == "session-1"


def test_fallback_is_visible_and_audited_before_the_child(
    monkeypatch,
    tmp_path,
    capsys,
):
    order = []
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, 17),
    )
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "ambient_session_id",
        lambda: "session-1",
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "with_source_pythonpath",
        lambda _env, _root: {"PYTHONPATH": "main-roots"},
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env: ({"yoke_core": str(tmp_path / "yoke_core")}, None),
    )

    def _record(**kwargs):
        order.append(("event", capsys.readouterr().err, kwargs))
        return None

    def _run(*args, **kwargs):
        order.append(("child", capsys.readouterr().err, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(source_dev_run, "_record_main_checkout_fallback", _record)
    monkeypatch.setattr(source_dev_run.subprocess, "run", _run)

    assert source_dev_run.run(["python3", "-c", "pass"]) == 0
    assert [entry[0] for entry in order] == ["event", "child"]
    assert f"source checkout: {tmp_path}" in order[0][1]
    assert "read-only" in order[0][1]
    assert "source imports:" in order[1][1]
    assert order[0][2]["session_id"] == "session-1"
    assert order[1][2]["cwd"] == str(tmp_path)


def test_fallback_refuses_to_run_without_audit_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, 17),
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env: ({"yoke_core": str(tmp_path / "yoke_core")}, None),
    )
    monkeypatch.setattr(
        source_dev_run,
        "_record_main_checkout_fallback",
        lambda **_kwargs: "event relay unavailable",
    )
    child = mock.Mock()
    monkeypatch.setattr(source_dev_run.subprocess, "run", child)

    assert source_dev_run.run(["python3", "-c", "pass"]) == 1
    child.assert_not_called()
