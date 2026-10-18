"""Give source imports and commands private copies of machine settings."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterator, Mapping

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV


def _home(env: Mapping[str, str]) -> Path:
    return Path(
        os.path.abspath(Path(env.get(HOME_ENV) or Path.home() / ".yoke").expanduser())
    )


def _snapshot(source: Path, destination: Path, selected: Path) -> None:
    """Copy settings and referenced files, never link mutable machine state.

    Caches, runtimes and live relay state are deliberately not cloned. Paths
    under the original home are rebased even when they do not exist yet, so
    later source writes create private state rather than touching the parent.
    """
    payload = (
        json.loads(selected.read_text(encoding="utf-8")) if selected.is_file() else {}
    )
    if not isinstance(payload, dict):
        raise ValueError("machine config must contain a JSON object")

    def rebase(value):
        if isinstance(value, dict):
            return {
                key: child if key == "checkout" else rebase(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [rebase(child) for child in value]
        if not isinstance(value, str):
            return value
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            return value
        candidate = Path(os.path.abspath(candidate))
        for origin in (source, source.resolve(), Path.home() / ".yoke"):
            try:
                relative = candidate.relative_to(origin)
                break
            except ValueError:
                continue
        else:
            return value
        target = destination / relative
        if candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(candidate, target)
            target.chmod(0o600)
        return str(target)

    secrets = source / "secrets"
    if secrets.is_dir():
        shutil.copytree(
            secrets, destination / "secrets", symlinks=False, dirs_exist_ok=True
        )
    payload = rebase(payload)
    payload.setdefault("temp_root", str(destination / "tmp"))
    payload.setdefault("cache_dir", str(destination / "cache"))
    target = destination / "config.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)


@contextmanager
def isolated_machine_home(
    env: Mapping[str, str], *, allow_real: bool = False
) -> Iterator[dict[str, str]]:
    """Keep the snapshot alive through probes and the complete child command."""
    resolved = dict(env)
    if allow_real:
        print(
            "source machine home: real (explicit --allow-real-machine-home)",
            file=sys.stderr,
        )
        yield resolved
        return
    source = _home(env)
    selected = source / "config.json"
    if not env.get(HOME_ENV) and env.get(CONFIG_FILE_ENV):
        selected = Path(env[CONFIG_FILE_ENV]).expanduser()
        if not selected.is_absolute():
            selected = source / selected
    with tempfile.TemporaryDirectory(prefix="yoke-source-machine-") as directory:
        destination = Path(directory)
        try:
            _snapshot(source, destination, selected)
        except (ValueError, OSError) as exc:
            raise OSError(
                f"cannot snapshot machine config {selected}; repair its JSON "
                "and read permissions"
            ) from exc
        resolved[HOME_ENV] = str(destination)
        resolved.pop(CONFIG_FILE_ENV, None)
        # Identity must survive moving away from the hook's process registry.
        if not resolved.get("YOKE_SESSION_ID"):
            from yoke_core.domain.session_ambient_identity import (
                resolve_ambient_session_id,
            )

            identity = resolve_ambient_session_id()
            if identity:
                resolved["YOKE_SESSION_ID"] = identity
        # macOS TMPDIR can exceed PostgreSQL's Unix socket path limit.
        evidence = Path(tempfile.mkdtemp(prefix="yoke-source-evidence-", dir="/tmp"))
        resolved["YOKE_SCRATCH_ROOT"] = str(evidence)
        print(f"source machine home: disposable {destination}", file=sys.stderr)
        print(f"source evidence root: {evidence}", file=sys.stderr)
        try:
            yield resolved
        finally:
            # Watcher captures must outlive the disposable settings they prove.
            try:
                evidence.rmdir()
            except OSError:
                pass
