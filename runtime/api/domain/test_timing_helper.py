from __future__ import annotations

from pathlib import Path

from yoke_core.domain.timing_helper import main


def _write_machine_config(tmp_path: Path, **settings: str) -> Path:
    config_path = tmp_path / ".yoke" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    pairs = ", ".join(f'"{key}": "{value}"' for key, value in settings.items())
    config_path.write_text(f'{{"settings": {{{pairs}}}}}\n', encoding="utf-8")
    return config_path


def test_enabled_reads_config(tmp_path: Path, capsys, monkeypatch) -> None:
    config_path = _write_machine_config(tmp_path, session_timing_enabled="true")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    assert main(["enabled", "--repo-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "true"


def test_init_and_mark_emit_shell_assignments(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    config_path = _write_machine_config(tmp_path, session_timing_enabled="true")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))

    assert main(["init", "myscript", "--repo-root", str(tmp_path), "--pid", "123"]) == 0
    init_output = capsys.readouterr().out
    assert "TIMING_LOG=" in init_output
    log_path = None
    for line in init_output.splitlines():
        if line.startswith("TIMING_LOG="):
            log_path = Path(line.split("=", 1)[1].strip("'"))
    assert log_path is not None and log_path.is_file()

    start = ""
    last = ""
    script = ""
    for line in init_output.splitlines():
        key, value = line.split("=", 1)
        value = value.strip("'")
        if key == "TIMING_START":
            start = value
        elif key == "TIMING_LAST":
            last = value
        elif key == "_TIMING_SCRIPT":
            script = value

    assert main(
        [
            "mark",
            "STEP1",
            "--timing-log",
            str(log_path),
            "--timing-start",
            start,
            "--timing-last",
            last,
            "--timing-script",
            script,
        ]
    ) == 0
    assert "TIMING_LAST=" in capsys.readouterr().out
    assert "myscript/STEP1" in log_path.read_text()
