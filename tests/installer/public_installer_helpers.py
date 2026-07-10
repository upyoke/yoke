from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = REPO_ROOT / "packaging" / "public-installer" / "install.py"
INSTALL_SHIM_PATH = REPO_ROOT / "packaging" / "public-installer" / "install"
RunResult = subprocess.CompletedProcess[str]


@pytest.fixture(autouse=True)
def branded_installer_glyphs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep branded install.py output independent of the runner terminal."""
    monkeypatch.setenv("YOKE_INSTALL_FORCE_PLAIN", "0")


def load_installer(name: str = "yoke_public_installer") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, INSTALLER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingRunner:
    """Records every command and replays a fixed result.

    A per-command override table lets a test return a specific stdout for, say,
    ``yoke status --json`` while every other command falls back to the default.
    """

    def __init__(
        self,
        *,
        rc: int = 0,
        stdout: str = "",
        stderr: str = "",
        responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.responses = responses or {}

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(command)
        self.commands.append(argv)
        override = self.responses.get(tuple(argv))
        if override is not None:
            return override
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


def write_channel(
    tmp_path: Path, *, version: str, channel: str = "stable"
) -> dict[str, object]:
    """Write a fake channels JSON file and return a ``file://`` base_url for it.

    The installer fetches ``{base_url}/dist/channels/{channel}.json`` and reads
    the ``version`` pin.
    """
    channels_dir = tmp_path / "site" / "dist" / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "channel": channel}
    (channels_dir / f"{channel}.json").write_text(json.dumps(payload), encoding="utf-8")
    return {
        "base_url": tmp_path.joinpath("site").as_uri(),
        "version": version,
        "channel": channel,
    }


def run_shim(
    bin_dir: Path,
    *,
    args: Sequence[str] = ("--dry-run",),
    env_extra: dict[str, str] | None = None,
    input_text: str | None = None,
) -> RunResult:
    # The fake uv stub execs a real python3 and the inline shell stubs use cat,
    # chmod, printf. Symlink the interpreter into bin_dir so python3 resolves
    # WITHOUT putting its own directory on PATH: on CI that directory is the
    # .venv/bin where `pip install uv` drops a real uv, which would leak past the
    # "uv absent" scenarios. bin_dir stays first so test stubs always win.
    python_exe = Path(sys.executable).resolve()
    for _name in ("python3", "python"):
        _link = bin_dir / _name
        if not _link.exists():
            _link.symlink_to(python_exe)
    path = ":".join([str(bin_dir), "/usr/bin", "/bin"])
    env = {
        "PATH": path,
        "YOKE_INSTALL_BASE_URL": "https://example.invalid",
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["/bin/sh", str(INSTALL_SHIM_PATH), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        input=input_text,
    )


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def write_uv_stub(bin_dir: Path, *, install_py_body: str | None = None) -> Path:
    """Write a fake ``uv`` that satisfies ``uv run --no-project python ...``.

    The shim runs the helper as ``uv run --no-project python <args>``; this stub
    strips the ``run --no-project python`` prefix and execs a real python3 so the
    tempdir probe, the install.py download, and the handoff all work without a
    real uv. When ``install_py_body`` is given, the stub serves it as the
    downloaded install.py instead of reaching the network.
    """
    path = bin_dir / "uv"
    serve = ""
    if install_py_body is not None:
        serve = (
            'if [ -n "${INSTALLER_OUT:-}" ]; then\n'
            '  cat > "$INSTALLER_OUT" <<\'INSTALL_PY_BODY\'\n'
            f"{install_py_body}\n"
            "INSTALL_PY_BODY\n"
            "  exit 0\n"
            "fi\n"
        )
    write_executable(
        path,
        "#!/bin/sh\n"
        'if [ "$1" = "run" ]; then\n'
        "  shift\n"
        '  while [ "$#" -gt 0 ]; do\n'
        '    case "$1" in\n'
        "      --no-project|--project|python) shift ;;\n"
        "      *) break ;;\n"
        "    esac\n"
        "  done\n"
        f"{serve}"
        '  exec python3 "$@"\n'
        "fi\n"
        "exit 0\n",
    )
    return path
