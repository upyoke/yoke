"""Launcher file and subprocess tests for ``install_yoke_launcher``."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.tools import install_yoke_launcher as isl


def test_refuse_foreign_binary_passes_when_target_absent(tmp_path: Path):
    isl.refuse_foreign_binary(tmp_path / "yoke")


def test_refuse_foreign_binary_accepts_existing_launcher(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "from yoke_cli.main import main\n"
    )
    isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_accepts_pip_console_script(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text(
        "#!/Users/x/venv/bin/python3\n"
        "import sys\n"
        "from yoke_cli.main import main\n"
        "sys.exit(main())\n"
    )
    isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_accepts_legacy_runtime_launcher(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "from runtime.api.cli.yoke_operations_cli import main\n"
    )
    isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_refuses_non_script(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_bytes(b"\x7fELF\x02\x01\x01\x00")
    with pytest.raises(isl.InstallError, match="not a python script"):
        isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_refuses_non_python_shebang(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text("#!/bin/bash\necho hi\n")
    with pytest.raises(isl.InstallError, match="not a python interpreter"):
        isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_refuses_missing_fingerprint(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text("#!/usr/bin/env python3\nprint('hello')\n")
    with pytest.raises(isl.InstallError, match="does not look like a Yoke launcher"):
        isl.refuse_foreign_binary(target)


def test_refuse_foreign_binary_force_overrides(tmp_path: Path):
    target = tmp_path / "yoke"
    target.write_text("#!/bin/bash\necho hi\n")
    isl.refuse_foreign_binary(target, force=True)


def test_write_launcher_copies_and_chmods(tmp_path: Path):
    source = tmp_path / "src.py"
    source.write_text("#!/usr/bin/env python3\nprint('launcher')\n")
    target = tmp_path / "bin" / "yoke"
    isl.write_launcher(target, source=source)
    assert target.is_file()
    text = target.read_text()
    assert text.startswith(f"#!{sys.executable}\n")
    assert "print('launcher')" in text
    assert (target.stat().st_mode & 0o777) == 0o755


def test_write_launcher_pins_shebang_to_active_python(tmp_path: Path):
    source = tmp_path / "src.py"
    source.write_text("#!/usr/bin/env python3\nimport sys\nprint(sys.executable)\n")
    target = tmp_path / "bin" / "yoke"
    isl.write_launcher(target, source=source)
    first_line = target.read_text().splitlines()[0]
    assert first_line == f"#!{sys.executable}"
    assert "/usr/bin/env" not in first_line


def test_write_launcher_handles_source_without_shebang(tmp_path: Path):
    source = tmp_path / "src.py"
    source.write_text("print('no-shebang launcher')\n")
    target = tmp_path / "bin" / "yoke"
    isl.write_launcher(target, source=source)
    text = target.read_text()
    assert text.startswith(f"#!{sys.executable}\n")
    assert "print('no-shebang launcher')" in text


def test_write_launcher_bakes_install_home_default(tmp_path: Path):
    target = tmp_path / "bin" / "yoke"
    home = tmp_path / "install-home"

    isl.write_launcher(target, default_home=home)

    text = target.read_text()
    assert f"DEFAULT_YOKE_HOME = {str(home)!r}" in text
    assert "os.environ.get(\"YOKE_HOME\")" in text


def test_written_launcher_loads_package_src_roots(tmp_path: Path):
    home = tmp_path / "home"
    cli_pkg = home / "packages" / "yoke-cli" / "src" / "yoke_cli"
    cli_pkg.mkdir(parents=True)
    (cli_pkg / "__init__.py").write_text("")
    (cli_pkg / "main.py").write_text(
        "import sys\n"
        "def main(argv):\n"
        "    print('\\n'.join(sys.path[:4]))\n"
        "    return 0\n"
    )
    target = tmp_path / "bin" / "yoke"
    isl.write_launcher(target)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["YOKE_HOME"] = str(home)
    result = subprocess.run(
        [str(target), "--version"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    loaded_paths = result.stdout.splitlines()
    assert str(home / "packages" / "yoke-cli" / "src") in loaded_paths[:4]


def test_verify_path_includes_returns_true_when_on_path(tmp_path: Path):
    target = tmp_path / "bin"
    target.mkdir()
    stream = io.StringIO()
    assert isl.verify_path_includes(target, env_path=str(target), stream=stream) is True
    assert stream.getvalue() == ""


def test_verify_path_includes_emits_rc_snippet_when_missing(tmp_path: Path):
    target = tmp_path / "bin"
    target.mkdir()
    stream = io.StringIO()
    assert isl.verify_path_includes(target, env_path="/usr/bin", stream=stream) is False
    out = stream.getvalue()
    assert "not on PATH" in out
    assert "~/.bashrc" in out
    assert "~/.zshrc" in out
    assert str(target) in out


def test_run_verification_checks_version_and_status():
    with mock.patch.object(isl.subprocess, "check_call") as cc:
        isl.run_verification()
    assert cc.call_args_list == [
        mock.call(["yoke", "--version"], env=mock.ANY),
        mock.call(["yoke", "status"], env=mock.ANY),
    ]


def test_run_verification_passes_explicit_env(monkeypatch):
    monkeypatch.delenv("YOKE_ENV", raising=False)
    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "check_call") as cc:
        isl.run_verification(verify_env="prod-db-admin", stream=stream)
    assert cc.call_args_list[0].kwargs["env"]["YOKE_ENV"] == "prod-db-admin"
    assert cc.call_args_list[1].kwargs["env"]["YOKE_ENV"] == "prod-db-admin"
    assert "YOKE_ENV=prod-db-admin" in stream.getvalue()
