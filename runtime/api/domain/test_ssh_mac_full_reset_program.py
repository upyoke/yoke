"""Filesystem behavior coverage for the uploaded Test Mac zsh program."""

from __future__ import annotations

from pathlib import Path
import shlex
import stat
import subprocess

from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    RESET_RELATIVE_DIRECTORIES,
    RESET_RELATIVE_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    STARTUP_FILE_NAMES,
    TOKEN_BACKUP_DIRECTORY,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


def _function_program() -> str:
    functions, separator, _main = FULL_RESET_SCRIPT.partition('\n[[ "$#" -eq 1 ]]\n')
    assert separator
    return functions


def _assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def test_zsh_program_opaquely_moves_evidence_and_restores_token_bytes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "test-home"
    home.mkdir()
    evidence = home / EVIDENCE_SOURCE_PATH / "campaign" / "report.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("retained-evidence", encoding="utf-8")
    yoke_config = home / ".yoke/config.json"
    yoke_config.write_text("remove", encoding="utf-8")
    ssh_file = home / ".ssh/authorized_keys"
    ssh_file.parent.mkdir()
    ssh_file.write_text("keep", encoding="utf-8")
    for suffix in RESET_RELATIVE_DIRECTORIES:
        target = home / suffix
        target.mkdir(parents=True)
        (target / "state").write_text("remove", encoding="utf-8")
    for suffix in RESET_RELATIVE_FILES:
        target = home / suffix
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("remove", encoding="utf-8")
    (home / "code/checkout/.git").mkdir(parents=True)
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": "/bin/zsh"}
    )
    tool_bin_suffix = Path(path_state.tool_bin_dir).relative_to(home)
    tool_bin_reference = f"$HOME/{tool_bin_suffix}"
    startup = home / STARTUP_FILE_NAMES[0]
    startup.write_text(
        "keep-before\n"
        f"{path_state.managed_begin}\nremove-managed\n"
        f"{path_state.managed_end}\n"
        "# uv was installed by uv\n"
        f'. "{tool_bin_reference}/env"\n'
        f'source "{tool_bin_reference}/env"\n'
        f'export PATH="{tool_bin_reference}:$PATH"\n'
        "keep-after\n",
        encoding="utf-8",
    )
    stage = tmp_path / "yoke-stage.token"
    prod = tmp_path / "yoke-prod.token"
    stage_bytes = b"stage-secret-byte-sequence"
    prod_bytes = b"prod-secret-byte-sequence"
    stage.write_bytes(stage_bytes)
    prod.write_bytes(prod_bytes)
    install_temp = tmp_path / "yoke-install"
    install_temp.write_text("remove", encoding="utf-8")
    backup = home / TOKEN_BACKUP_DIRECTORY
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("tool_bin_dir", path_state.tool_bin_dir),
        f"reset_temp_files=({shlex.quote(str(install_temp))})",
        _assignment("stage_source", str(stage)),
        _assignment("prod_source", str(prod)),
        _assignment("token_backup_directory", str(backup)),
        _assignment("stage_backup", str(backup / "yoke-stage.token")),
        _assignment("prod_backup", str(backup / "yoke-prod.token")),
        _assignment("stage_backup_temporary", str(backup / ".stage.reset-tmp")),
        _assignment("prod_backup_temporary", str(backup / ".prod.reset-tmp")),
        _assignment("stage_restore_temporary", str(tmp_path / ".stage.restore-tmp")),
        _assignment("prod_restore_temporary", str(tmp_path / ".prod.restore-tmp")),
        _assignment("evidence_source", str(home / EVIDENCE_SOURCE_PATH)),
        _assignment(
            "retained_evidence_root",
            str(home / RETAINED_EVIDENCE_DIRECTORY),
        ),
        "stage_saved=0",
        "prod_saved=0",
        'evidence_outcome="ABSENT"',
        'evidence_container=""',
        "preserve_tokens",
        "remove_registered_state",
        "clean_startup_files",
        "restore_tokens",
        "cleanup_scratch",
    )

    result = subprocess.run(
        ["/bin/zsh"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (home / ".yoke").exists()
    moved = tuple(
        (home / RETAINED_EVIDENCE_DIRECTORY).glob(
            "reset.*/installer-smoke-evidence/campaign/report.json"
        )
    )
    assert len(moved) == 1
    assert moved[0].read_text(encoding="utf-8") == "retained-evidence"
    assert ssh_file.read_text(encoding="utf-8") == "keep"
    assert all(not (home / suffix).exists() for suffix in RESET_RELATIVE_DIRECTORIES)
    assert all(not (home / suffix).exists() for suffix in RESET_RELATIVE_FILES)
    assert not install_temp.exists()
    assert list((home / "code").iterdir()) == []
    assert startup.read_text(encoding="utf-8") == "keep-before\nkeep-after\n"
    assert stage.read_bytes() == stage_bytes
    assert prod.read_bytes() == prod_bytes
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert (backup / "yoke-stage.token").read_bytes() == stage_bytes
    assert stat.S_IMODE((backup / "yoke-stage.token").stat().st_mode) == 0o600
