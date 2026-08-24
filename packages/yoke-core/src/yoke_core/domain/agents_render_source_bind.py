"""Bind agents-render imports to the target checkout.

A process that loaded ``yoke_core`` from main and then checked or wrote a
different Yoke-shaped tree compared the wrong seed to that tree's rendered
files. ``watch_pytest`` binds ``PYTHONPATH`` before launching its child;
this module does the same for the renderer and refuses if the bound child
is still mixed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, Mapping

from yoke_core.domain.workspace_authority import assert_seed_source_under_target_root
from yoke_core.tools import _source_pythonpath

RENDER_SOURCE_BOUND_ENV = "YOKE_RENDER_SOURCE_BOUND"
RendererMode = Literal["check", "render", "dry-run"]

_CHILD = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from yoke_core.domain.agents_render import (\n"
    "    detect_substrate_drift, write_all_and_record,\n"
    ")\n"
    "req = json.load(sys.stdin)\n"
    "root = Path(req['target_root'])\n"
    "mode = req['mode']\n"
    "if mode == 'check':\n"
    "    json.dump({'kind': 'check', 'drift': list("
    "detect_substrate_drift(target_root=root))}, sys.stdout)\n"
    "else:\n"
    "    rendered = write_all_and_record("
    "target_root=root, dry_run=(mode == 'dry-run'))\n"
    "    json.dump({'kind': 'render', 'results': {"
    "rel: action for rel, (action, _) in rendered.items()}}, sys.stdout)\n"
)


def assert_renderer_seed(target_root: Path) -> None:
    """Refuse when the imported seed belongs to a different Yoke checkout."""
    from yoke_core.domain import schema_api_context_seed as _seed

    assert_seed_source_under_target_root(
        getattr(_seed, "__file__", None),
        target_root,
        seed_module_name="schema_api_context_seed",
        require_session=False,
    )


def current_core_origin() -> Path:
    import yoke_core

    return Path(yoke_core.__file__).resolve()


def mixed_renderer_source(target_root: Path) -> tuple[Path, Path] | None:
    """Return ``(origin, target)`` when a Yoke-shaped target would use the wrong tree."""
    root = Path(target_root).resolve()
    if not _source_pythonpath.is_yoke_shaped_tree(root):
        return None
    origin = current_core_origin()
    try:
        origin.relative_to(root)
    except ValueError:
        return origin, root
    return None


def mixed_source_message(origin: Path, target: Path) -> str:
    return (
        f"agents render source mismatch: seed loaded from {origin}, "
        f"target is {target}. Repair: `{_source_pythonpath.SOURCE_RUN_RECIPE}` "
        "so both origins match, or re-run `yoke agents render` so it binds "
        "PYTHONPATH to the target checkout."
    )


def invoke_renderer(*, target_root: Path, mode: RendererMode) -> Any:
    """Run check or render against ``target_root`` with matching seed origin."""
    mixed = mixed_renderer_source(target_root)
    if mixed is None:
        return _run_inprocess(target_root, mode)
    origin, root = mixed
    if os.environ.get(RENDER_SOURCE_BOUND_ENV) == "1":
        raise RuntimeError(mixed_source_message(origin, root))
    return _run_bound_child(root, mode, origin=origin)


def reexec_cli_if_mixed(target_root: Path) -> None:
    """Re-exec ``python -m yoke_core.domain.agents_render`` bound to ``target_root``."""
    mixed = mixed_renderer_source(target_root)
    if mixed is None:
        return
    origin, root = mixed
    if os.environ.get(RENDER_SOURCE_BOUND_ENV) == "1":
        print(mixed_source_message(origin, root), file=sys.stderr)
        raise SystemExit(2)
    env = _bound_env(root)
    refusal = _source_pythonpath.import_origin_refusal(root, env=env)
    if refusal is not None:
        print(f"{mixed_source_message(origin, root)} {refusal}", file=sys.stderr)
        raise SystemExit(2)
    completed = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.agents_render", *sys.argv[1:]],
        env=env,
        cwd=str(root),
        check=False,
    )
    raise SystemExit(int(completed.returncode))


def _bound_env(root: Path) -> dict[str, str]:
    env = _source_pythonpath.with_source_pythonpath(None, root)
    env[RENDER_SOURCE_BOUND_ENV] = "1"
    return env


def _run_inprocess(target_root: Path, mode: RendererMode) -> Any:
    from yoke_core.domain.agents_render import (
        detect_substrate_drift,
        write_all_and_record,
    )

    if mode == "check":
        return list(detect_substrate_drift(target_root=target_root))
    rendered = write_all_and_record(
        target_root=target_root, dry_run=(mode == "dry-run")
    )
    return {rel: action for rel, (action, _content) in rendered.items()}


def _run_bound_child(root: Path, mode: RendererMode, *, origin: Path) -> Any:
    env = _bound_env(root)
    refusal = _source_pythonpath.import_origin_refusal(root, env=env)
    if refusal is not None:
        raise RuntimeError(f"{mixed_source_message(origin, root)} {refusal}")
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD],
        input=json.dumps({"target_root": str(root), "mode": mode}),
        env=env,
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "no renderer output"
        raise RuntimeError(
            f"{mixed_source_message(origin, root)} bound child exited "
            f"{completed.returncode}: {detail}"
        )
    try:
        payload: Mapping[str, Any] = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{mixed_source_message(origin, root)} bound child returned "
            "unreadable JSON"
        ) from exc
    if payload.get("kind") == "check":
        return list(payload.get("drift") or [])
    results = payload.get("results")
    if not isinstance(results, dict):
        raise RuntimeError(
            f"{mixed_source_message(origin, root)} bound child omitted results"
        )
    return {str(rel): str(action) for rel, action in results.items()}


__all__ = [
    "RENDER_SOURCE_BOUND_ENV",
    "assert_renderer_seed",
    "current_core_origin",
    "invoke_renderer",
    "mixed_renderer_source",
    "mixed_source_message",
    "reexec_cli_if_mixed",
]
