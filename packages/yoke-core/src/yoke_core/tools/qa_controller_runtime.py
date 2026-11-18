"""Provision a disposable candidate Yoke runtime for release-run QA controllers.

The runtime is a private virtual environment holding exactly the candidate's
four published wheels, under ``<yoke home>/qa-controller-runtimes``. It is
installed with ``pip --isolated`` beside, never over, the machine's installed
CLI: no channel, PATH, settings or hook is touched. A verified runtime is
reused by later controller commands (the walker's mission commands) and the
least recently used ones beyond :data:`RETAINED_RUNTIMES` are removed.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yoke_contracts.machine_config.paths import yoke_home
from yoke_contracts import platform_file_lock as locks
from yoke_contracts.platform_fs import remove_tree
from yoke_core.domain.relay_release_path import relay_venv_executable, relay_venv_python
from yoke_core.tools.distribution_channel import join_public_url

RUNTIMES_DIR_NAME = "qa-controller-runtimes"
RECEIPT_NAME = "controller-runtime.json"
LOCK_NAME = ".install.lock"
RETAINED_RUNTIMES = 3
#: The candidate module a handed-off controller runs; absent in releases that
#: predate the handoff, which therefore cannot serve as a candidate runtime.
HANDOFF_MODULE = "yoke_core.domain.qa_controller_handoff_cli"
_WHEELS = ("contracts", "cli", "harness", "core")
_INSTALL_TIMEOUT_SECONDS = 900

Runner = Callable[..., subprocess.CompletedProcess[str]]


class ControllerRuntimeError(RuntimeError):
    """The candidate runtime could not be provisioned or verified."""


@dataclass(frozen=True)
class ControllerRuntime:
    root: Path
    python: Path
    executable: Path
    version: str
    source_commit: str


def runtimes_root() -> Path:
    return yoke_home() / RUNTIMES_DIR_NAME


def _runtime(root: Path, version: str, commit: str) -> ControllerRuntime:
    return ControllerRuntime(
        root, relay_venv_python(root), relay_venv_executable(root), version, commit
    )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    text = str(result.stderr or result.stdout or f"exit {result.returncode}")
    return " ".join(text.split())[-800:]


def _site_packages(root: Path) -> list[Path]:
    # The venv is built by this interpreter, so its venv scheme names the layout.
    scheme = "venv" if "venv" in sysconfig.get_scheme_names() else None
    paths = sysconfig.get_paths(
        **({"scheme": scheme} if scheme else {}),
        vars={"base": str(root), "platbase": str(root)},
    )
    return [Path(paths["purelib"])]


def verify_runtime(root: Path, version: str, commit: str) -> str:
    """Why *root* is not the candidate runtime, or ``""`` when it is."""
    if not relay_venv_python(root).is_file() or not relay_venv_executable(root).is_file():
        return f"{root} has no python and yoke executables"
    if not (root / RECEIPT_NAME).is_file():
        return f"{root} has no install receipt; it was not installed in place"
    head = relay_venv_executable(root).read_bytes()[:512]
    if head.startswith(b"#!") and str(root).encode() not in head.split(b"\n", 1)[0]:
        return f"{relay_venv_executable(root)} launches an interpreter outside {root}"
    found = list(
        importlib.metadata.distributions(
            name="yoke-core", path=[str(p) for p in _site_packages(root)]
        )
    )
    if len(found) != 1:
        return f"{root} holds {len(found)} yoke-core distributions, not one"
    dist = found[0]
    if dist.version != version:
        return f"{root} holds yoke-core {dist.version}, not {version}"
    record = Path(str(dist.locate_file(f"yoke_core-{version}.dist-info/scm_version.json")))
    try:
        node = str(json.loads(record.read_text(encoding="utf-8")).get("node"))
    except (OSError, ValueError, AttributeError):
        node = ""
    built = node[1:] if node.startswith("g") else node
    if built != commit:
        return f"yoke-core {version} was built from {built[:12] or 'an unrecorded commit'}, not {commit[:12]}"
    module = HANDOFF_MODULE.replace(".", "/") + ".py"
    if not any(str(f) == module for f in dist.files or ()):
        return (
            f"Yoke {version} predates the candidate-controller handoff "
            f"({HANDOFF_MODULE} is absent), so it cannot drive this QA"
        )
    return ""


def _install(root: Path, *, base_url: str, version: str, runner: Runner) -> None:
    created = runner(
        [sys.executable, "-I", "-m", "venv", str(root)],
        check=False, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_SECONDS,
    )
    if created.returncode != 0:
        raise ControllerRuntimeError(f"could not create a venv: {_detail(created)}")
    wheels = [
        join_public_url(
            base_url, "dist", "releases", version, "wheels",
            f"yoke_{name}-{version}-py3-none-any.whl",
        )
        for name in _WHEELS
    ]
    installed = runner(
        [
            str(relay_venv_python(root)), "-I", "-m", "pip", "--isolated", "install",
            "--disable-pip-version-check", "--no-input", "--only-binary", ":all:",
            *wheels,
        ],
        check=False, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_SECONDS,
    )
    if installed.returncode != 0:
        raise ControllerRuntimeError(
            f"could not install Yoke {version} wheels from {base_url}: {_detail(installed)}"
        )


def ensure_controller_runtime(
    *, base_url: str, version: str, source_commit: str, runner: Runner = subprocess.run
) -> ControllerRuntime:
    """The verified candidate runtime, installing it when absent or broken.

    It installs in place: a venv's console scripts name its interpreter by
    absolute path, so a venv built elsewhere and renamed would break ``yoke``.
    A lock serializes concurrent controllers installing the same runtime.
    """
    parent = runtimes_root()
    root = parent / f"{version}-{source_commit[:12]}"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with (parent / LOCK_NAME).open(mode="a+b") as handle:
            locks.acquire_exclusive(handle.fileno())
            try:
                if verify_runtime(root, version, source_commit):
                    _install_in_place(
                        root, base_url=base_url, version=version,
                        source_commit=source_commit, runner=runner,
                    )
                else:
                    os.utime(root)
            finally:
                locks.release_exclusive(handle.fileno())
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControllerRuntimeError(f"{type(exc).__name__}: {exc}") from exc
    _prune(parent, keep=root)
    return _runtime(root, version, source_commit)


def _install_in_place(
    root: Path, *, base_url: str, version: str, source_commit: str, runner: Runner
) -> None:
    if root.exists():
        remove_tree(root)
    installed = False
    try:
        _install(root, base_url=base_url, version=version, runner=runner)
        (root / RECEIPT_NAME).write_text(
            json.dumps(
                {"version": version, "source_commit": source_commit, "base_url": base_url},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        reason = verify_runtime(root, version, source_commit)
        if reason:
            raise ControllerRuntimeError(reason)
        installed = True
    finally:
        if not installed and root.exists():
            remove_tree(root)


def _prune(parent: Path, *, keep: Path) -> None:
    try:
        runtimes = [p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return
    runtimes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in [p for p in runtimes if p != keep][RETAINED_RUNTIMES - 1 :]:
        try:
            remove_tree(stale)
        except OSError:
            pass


__all__ = [
    "ControllerRuntime",
    "ControllerRuntimeError",
    "HANDOFF_MODULE",
    "RETAINED_RUNTIMES",
    "ensure_controller_runtime",
    "runtimes_root",
    "verify_runtime",
]
