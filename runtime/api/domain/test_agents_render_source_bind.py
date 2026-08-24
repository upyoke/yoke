"""Cross-checkout source binding for agents render.

Covers the false-drift shape: seed loaded from one Yoke checkout while
``target_root`` names another. Check and dry-run must refuse instead of
comparing those trees; ``invoke_renderer`` rebinds PYTHONPATH for a
Yoke-shaped target whose origin is outside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)
from yoke_core.domain.agents_render import detect_substrate_drift, write_all
from yoke_core.domain.agents_render_source_bind import (
    RENDER_SOURCE_BOUND_ENV,
    invoke_renderer,
    mixed_renderer_source,
    mixed_source_message,
)
from yoke_core.domain.workspace_authority import (
    SESSION_ID_ENV_VAR,
    assert_seed_source_under_target_root,
)

YOKE_CORE_MARKER = Path("packages") / "yoke-core" / "src" / "yoke_core"
LANE_SEED_REL = (
    Path("packages") / "yoke-core" / "src" / "yoke_core" / "domain"
    / "schema_api_context_seed.py"
)


def _yoke_shaped_lane(tmp_path: Path) -> Path:
    lane = tmp_path / "lane"
    (lane / YOKE_CORE_MARKER).mkdir(parents=True)
    seed = lane / LANE_SEED_REL
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("# lane seed\n")
    return lane


def _not_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.workspace_authority._is_free_path",
        lambda _path: False,
    )


def test_mixed_source_none_for_live_checkout() -> None:
    root = resolve_live_repo_root()
    assert mixed_renderer_source(root) is None


def test_mixed_source_none_for_external_tree(tmp_path: Path) -> None:
    assert mixed_renderer_source(tmp_path / "external") is None


def test_mixed_source_reports_other_yoke_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _yoke_shaped_lane(tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind.current_core_origin",
        lambda: Path("/opt/main/packages/yoke-core/src/yoke_core/__init__.py"),
    )
    mixed = mixed_renderer_source(lane)
    assert mixed is not None
    origin, root = mixed
    assert origin.as_posix().endswith("yoke_core/__init__.py")
    assert root == lane.resolve()
    message = mixed_source_message(origin, root)
    assert str(origin) in message
    assert str(root) in message
    assert "yoke dev run" in message


def test_detect_substrate_drift_refuses_mixed_yoke_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _not_free(monkeypatch)
    lane = _yoke_shaped_lane(tmp_path)
    with pytest.raises(RuntimeError, match="seed-source mismatch"):
        detect_substrate_drift(target_root=lane)


def test_write_all_dry_run_refuses_mixed_yoke_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _not_free(monkeypatch)
    lane = _yoke_shaped_lane(tmp_path)
    with pytest.raises(RuntimeError, match="seed-source mismatch"):
        write_all(target_root=lane, dry_run=True)


def test_ungated_seed_check_refuses_without_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SESSION_ID_ENV_VAR, raising=False)
    _not_free(monkeypatch)
    lane = _yoke_shaped_lane(tmp_path)
    main_seed = tmp_path / "main" / LANE_SEED_REL
    main_seed.parent.mkdir(parents=True)
    main_seed.write_text("# main seed\n")
    with pytest.raises(RuntimeError, match="seed-source mismatch"):
        assert_seed_source_under_target_root(
            str(main_seed),
            lane,
            seed_module_name="schema_api_context_seed",
            require_session=False,
        )


def test_invoke_renderer_same_tree_stays_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = resolve_live_repo_root()
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind._run_bound_child",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("same-tree render must not spawn a bound child")
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind._run_inprocess",
        lambda _target, mode: [] if mode == "check" else {"x": "skip"},
    )
    assert invoke_renderer(target_root=root, mode="check") == []


def test_invoke_renderer_rebinds_mixed_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _yoke_shaped_lane(tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind.current_core_origin",
        lambda: Path("/opt/main/packages/yoke-core/src/yoke_core/__init__.py"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind._source_pythonpath.import_origin_refusal",
        lambda _root, env: None,
    )
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        captured["input"] = kwargs.get("input")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"kind": "check", "drift": []}),
            stderr="",
        )

    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind.subprocess.run",
        fake_run,
    )
    assert invoke_renderer(target_root=lane, mode="check") == []
    assert captured["cwd"] == str(lane.resolve())
    env = captured["env"]
    assert isinstance(env, dict)
    assert env.get(RENDER_SOURCE_BOUND_ENV) == "1"


def test_invoke_renderer_refuses_when_already_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _yoke_shaped_lane(tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_source_bind.current_core_origin",
        lambda: Path("/opt/main/packages/yoke-core/src/yoke_core/__init__.py"),
    )
    monkeypatch.setenv(RENDER_SOURCE_BOUND_ENV, "1")
    with pytest.raises(RuntimeError, match="source mismatch"):
        invoke_renderer(target_root=lane, mode="check")
