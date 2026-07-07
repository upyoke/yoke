import json

from runtime.harness.claude.merge_settings import main, merge_settings


def test_merge_settings_adds_rules_and_hooks(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{}\n", encoding="utf-8")

    merge_settings(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == [
        "Bash",
        "Write(**)",
        "Edit(**)",
        "Read(*)",
        "Grep(*)",
        "Glob(*)",
    ]
    assert "UserPromptSubmit" in data["hooks"]
    assert "Stop" in data["hooks"]
    assert "SessionEnd" in data["hooks"]


def test_merge_settings_is_idempotent_and_preserves_existing_order(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Custom(*)", "Read(*)"]},
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 -m runtime.harness.hook_runner Stop",
                                }
                            ]
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    merge_settings(str(target))
    merge_settings(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"][0] == "Custom(*)"
    assert data["permissions"]["allow"].count("Read(*)") == 1
    assert len(data["hooks"]["Stop"]) == 1


def test_main_invalid_json_reports_error(tmp_path, capsys):
    target = tmp_path / "settings.json"
    target.write_text("{invalid", encoding="utf-8")

    rc = main([str(target)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "invalid JSON" in captured.err


def test_main_help_flag_does_not_create_help_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    for flag in ("--help", "-h"):
        rc = main([flag])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert not (tmp_path / flag).exists(), (
            f"merge_settings {flag} wrote a file named {flag!r} in cwd "
            "instead of printing usage; this is the stray --help artifact bug."
        )
