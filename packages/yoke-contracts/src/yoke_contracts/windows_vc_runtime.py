"""The Microsoft Visual C++ runtime DLLs the embedded Windows engine loads.

A PE import walk of ``postgresql-17.11.1-x86_64-pc-windows-msvc`` found that
every engine tool imports ``vcruntime140.dll``, and that ``initdb.exe`` and
``postgres.exe`` import ICU (``icuuc78.dll``, ``icuin78.dll``), which imports
``msvcp140.dll`` and ``vcruntime140_1.dll``. The engine bundles none of them
and names the runtime as a system dependency.

When System32 lacks one of them, Yoke installs it app-local in the engine
``bin`` from Microsoft's pinned VC++ 2015-2022 x64 redistributable, which
Microsoft permits. Nothing is installed system-wide, so a standard user
needs no elevation. Read-only and stdlib, safe to import on every OS.
"""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import Callable, Mapping
import urllib.error
import urllib.request

#: Needed DLL name -> sha256 of the copy the pinned redistributable carries.
RUNTIME_DLLS = {
    "vcruntime140.dll": "d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066",
    "vcruntime140_1.dll": "1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f",
    "msvcp140.dll": "0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9",
}

REDIST_HOST = "download.visualstudio.microsoft.com"
#: Microsoft's versioned URL for the redistributable
#: ``https://aka.ms/vs/17/release/vc_redist.x64.exe`` served when it was pinned.
REDIST_URL = (
    f"https://{REDIST_HOST}/download/pr/e9604e21-4b79-4096-a4b3-1b63d4b55b4d/"
    "CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/"
    "VC_redist.x64.exe"
)
REDIST_SHA256 = "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b"

#: Byte range of the Burn attached container (a cabinet) inside the pinned
#: redistributable: its ``.wixburn`` section's original signature offset
#: plus size, and the container's recorded size.
CONTAINER_OFFSET = 686152
CONTAINER_SIZE = 24939223
#: Container member holding ``packages\vcRuntimeMinimum_amd64\cab1.cab``,
#: whose members are the runtime DLLs named with this suffix.
RUNTIME_CABINET = "a12"
MEMBER_SUFFIX = "_amd64"

INSTALL_STEP = (
    f"Allow {REDIST_HOST} through the proxy or firewall, or ask an "
    "administrator to run `winget install --id Microsoft.VCRedist.2015+.x64 -e`"
)


def system32(environ: Mapping[str, str]) -> str:
    return ntpath.join(environ.get("SystemRoot") or r"C:\Windows", "System32")


def missing_dlls(bin_dir: str | Path | None, environ: Mapping[str, str]) -> list[str]:
    """Needed DLLs that neither System32 nor the engine ``bin`` holds."""
    root = system32(environ)
    return [
        name
        for name in RUNTIME_DLLS
        if not os.path.isfile(ntpath.join(root, name))
        and not (bin_dir is not None and (Path(bin_dir) / name).is_file())
    ]


def redist_reachable(timeout: float = 2.0) -> bool:
    """Whether the pinned redistributable answers a HEAD request."""
    request = urllib.request.Request(REDIST_URL, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def runtime_source(
    bin_dir: str | Path | None,
    environ: Mapping[str, str],
    *,
    reachable: Callable[[], bool] | None = None,
) -> tuple[str | None, list[str]]:
    """Where every needed DLL comes from, else ``(None, DLLs with no source)``."""
    missing = missing_dlls(bin_dir, environ)
    if not missing:
        return "present in System32 or the engine bin", []
    if (reachable or redist_reachable)():
        return (
            f"{', '.join(missing)} installed into the engine bin from "
            "Microsoft's VC++ redistributable on the first local start",
            [],
        )
    return None, missing


def unsourced_problem(missing: list[str]) -> str:
    """The refusal for needed DLLs that no source can supply."""
    return (
        f"Microsoft Visual C++ runtime ({', '.join(missing)}) is missing and "
        f"Microsoft's redistributable at {REDIST_HOST} is unreachable; the local "
        f"Yoke universe's embedded Postgres cannot start. {INSTALL_STEP}, then "
        "rerun setup."
    )


__all__ = [
    "CONTAINER_OFFSET",
    "CONTAINER_SIZE",
    "INSTALL_STEP",
    "MEMBER_SUFFIX",
    "REDIST_HOST",
    "REDIST_SHA256",
    "REDIST_URL",
    "RUNTIME_CABINET",
    "RUNTIME_DLLS",
    "missing_dlls",
    "redist_reachable",
    "runtime_source",
    "system32",
    "unsourced_problem",
]
