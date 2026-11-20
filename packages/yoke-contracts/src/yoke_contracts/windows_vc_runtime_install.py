"""Install the MSVC runtime DLLs app-local in the Windows engine ``bin``.

Runs after an engine unpack and before every local start, so an engine
installed before this step existed, or one whose DLLs were deleted, is
repaired. Only the DLLs neither System32 nor ``bin`` holds are installed.
They come from Microsoft's pinned redistributable
(:mod:`yoke_contracts.windows_vc_runtime`): its sha256 is verified, the
runtime cabinet is unpacked with Windows' inbox ``tar.exe`` (no elevation),
and each DLL is checked against its pinned sha256 before it lands in ``bin``.
Contracts-only imports: the image build runs the engine fetch from source.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import secrets
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional

from yoke_contracts import windows_vc_runtime as runtime
from yoke_contracts.owner_private_path import create_owner_private_directory
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.resilient_fetch import FetchError, fetch_bytes

_WINDOWS = os.name == "nt"
_FETCH_TIMEOUT_S = 120
_TAR_TIMEOUT_S = 120


class VcRuntimeError(RuntimeError):
    """The runtime DLLs could not be installed into the engine ``bin``."""


def ensure_runtime(
    bin_dir: Path,
    *,
    environ: Optional[Mapping[str, str]] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> list[str]:
    """Install each needed DLL ``bin_dir`` lacks; return the names installed."""
    if not _WINDOWS:
        return []
    selected_env = os.environ if environ is None else environ
    missing = runtime.missing_dlls(bin_dir, selected_env)
    if not missing:
        return []
    emit(
        f"  [postgres-binaries] installing {', '.join(missing)} from "
        f"Microsoft's VC++ redistributable into {bin_dir}"
    )
    try:
        staging = create_owner_private_directory(
            bin_dir.parent / (".vc-runtime-" + secrets.token_hex(12))
        )
    except OSError as exc:
        raise _failure(missing, bin_dir, str(exc)) from exc
    try:
        container = staging / "container.cab"
        container.write_bytes(_fetch_container())
        _extract(container, staging, [runtime.RUNTIME_CABINET], selected_env)
        _extract(
            staging / runtime.RUNTIME_CABINET,
            staging,
            [name + runtime.MEMBER_SUFFIX for name in missing],
            selected_env,
        )
        # Verify the whole set before any lands, so bin never mixes versions.
        verified = {
            name: _verified(staging / (name + runtime.MEMBER_SUFFIX), name)
            for name in missing
        }
        for name, data in verified.items():
            _install(data, bin_dir / name)
    except (FetchError, OSError, subprocess.SubprocessError, ValueError) as exc:
        raise _failure(missing, bin_dir, str(exc)) from exc
    finally:
        remove_tree(staging)
    emit(f"  [postgres-binaries] installed {', '.join(missing)} into {bin_dir}")
    return missing


def _fetch_container() -> bytes:
    """The redistributable's attached container, after its sha256 verifies."""
    body = fetch_bytes(
        runtime.REDIST_URL,
        timeout=_FETCH_TIMEOUT_S,
        expected_sha256=runtime.REDIST_SHA256,
    ).body
    end = runtime.CONTAINER_OFFSET + runtime.CONTAINER_SIZE
    container = body[runtime.CONTAINER_OFFSET:end]
    if len(container) != runtime.CONTAINER_SIZE or container[:4] != b"MSCF":
        raise ValueError("the redistributable carries no runtime cabinet at its pinned offset")
    return container


def _extract(
    archive: Path,
    dest: Path,
    members: list[str],
    environ: Mapping[str, str],
) -> None:
    """Unpack *members* of a cabinet with Windows' inbox ``tar.exe``."""
    tar = ntpath.join(runtime.system32(environ), "tar.exe")
    result = subprocess.run(
        [tar, "-x", "-f", str(archive), "-C", str(dest), *members],
        capture_output=True,
        text=True,
        timeout=_TAR_TIMEOUT_S,
    )
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()[:400]
        raise ValueError(f"{tar} exited {result.returncode} unpacking {archive.name}: {reason}")


def _verified(source: Path, name: str) -> bytes:
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != runtime.RUNTIME_DLLS[name]:
        raise ValueError(f"{name} from the redistributable failed its sha256 check")
    return data


def _install(data: bytes, target: Path) -> None:
    """Publish one verified DLL atomically in ``bin``."""
    # Written inside bin so the file inherits the engine's owner-private ACL.
    temp = target.with_name(f".{target.name}.{secrets.token_hex(6)}")
    try:
        temp.write_bytes(data)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _failure(missing: list[str], bin_dir: Path, reason: str) -> VcRuntimeError:
    return VcRuntimeError(
        f"embedded_postgres_vc_runtime_unavailable: could not install "
        f"{', '.join(missing)} into {bin_dir} from {runtime.REDIST_URL}: "
        f"{reason}. {runtime.INSTALL_STEP}; then retry `yoke local-postgres start`."
    )


__all__ = ["VcRuntimeError", "ensure_runtime"]
