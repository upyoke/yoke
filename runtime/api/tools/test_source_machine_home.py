"""Source imports and children may mutate only their disposable settings."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_core.domain.source_python_environment import SourcePythonEnvironment
from yoke_core.tools import source_dev_run
from yoke_core.tools.source_machine_home import isolated_machine_home


def _seed(home):
    home.mkdir()
    token = home / "secrets" / "connection.token"
    token.parent.mkdir()
    token.write_text("fixture-token")
    (token.parent / "capability-token").write_text("capability-fixture")
    config = home / "config.json"
    config.write_text(
        json.dumps(
            {
                "settings": {"configured": "yes"},
                "projects": [{"checkout": str(home / "source"), "project_id": 7}],
                "credential": str(token),
                "temp_root": str(home / "tmp"),
                "cache_dir": str(home / "cache"),
            }
        )
    )
    return config, config.read_bytes(), token


def test_source_probe_and_child_writes_leave_parent_byte_identical(
    tmp_path, monkeypatch
):
    home = tmp_path / "machine"
    config, original, token = _seed(home)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "stale.json"))
    monkeypatch.setenv("YOKE_SESSION_ID", "fixture-session")
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None, None))
    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(sys.executable, env, {}),
    )
    probe_home = []

    def probe(root, *, env, python):
        isolated = Path(env["YOKE_MACHINE_HOME"])
        probe_home.append(isolated)
        payload = json.loads((isolated / "config.json").read_text())
        assert payload["settings"] == {"configured": "yes"}
        assert (
            isolated / "secrets" / "capability-token"
        ).read_text() == "capability-fixture"
        assert Path(payload["credential"]).read_text() == "fixture-token"
        Path(payload["credential"]).write_text("probe-write")
        (isolated / "config.json").write_text('{"probe": true}')
        assert "YOKE_MACHINE_CONFIG_FILE" not in env
        return {}, None

    monkeypatch.setattr(source_dev_run._source_pythonpath, "import_origins", probe)
    code = (
        "import os,pathlib; "
        "p=pathlib.Path(os.environ['YOKE_MACHINE_HOME'])/'config.json'; "
        "assert p.read_text() == '{\"probe\": true}'; "
        "p.write_text('{\"child\": true}')"
    )
    assert source_dev_run.run(["python3", "-c", code]) == 0
    assert config.read_bytes() == original
    assert token.read_text() == "fixture-token"
    assert not probe_home[0].exists()


def test_explicit_opt_in_uses_the_selected_real_home(tmp_path):
    config, _, _ = _seed(tmp_path / "machine")
    env = {**os.environ, "YOKE_MACHINE_HOME": str(config.parent)}
    with isolated_machine_home(env, allow_real=True) as child:
        assert child == env
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import os; "
                "(Path(os.environ['YOKE_MACHINE_HOME'])/'config.json').write_text('{}')",
            ],
            env=child,
            check=True,
        )
    assert config.read_text() == "{}"


@pytest.mark.parametrize("config_override", [False, True])
def test_snapshot_selects_explicit_config_and_rebases_default_paths(
    tmp_path, config_override
):
    config, original, _ = _seed(tmp_path / "machine")
    env = {"YOKE_SESSION_ID": "fixture-session"}
    if config_override:
        env["YOKE_MACHINE_CONFIG_FILE"] = str(config)
    else:
        env["YOKE_MACHINE_HOME"] = str(config.parent)
    with isolated_machine_home(env) as child:
        target = Path(child["YOKE_MACHINE_HOME"])
        payload = json.loads((target / "config.json").read_text())
        assert payload["settings"] == {"configured": "yes"}
        if not config_override:
            assert payload["temp_root"] == str(target / "tmp")
            assert payload["cache_dir"] == str(target / "cache")
    assert config.read_bytes() == original


def test_snapshot_failure_is_named_and_does_not_launch_child(
    tmp_path, monkeypatch, capsys
):
    config, _, _ = _seed(tmp_path / "machine")
    config.write_text("invalid json")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(config.parent))
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None, None))
    assert (
        source_dev_run.run(["python3", "-c", "raise AssertionError('launched')"]) == 1
    )
    assert "source_machine_home_unavailable" in capsys.readouterr().err


def test_symlinked_machine_home_rebases_both_aliases(tmp_path):
    config, original, token = _seed(tmp_path / "machine")
    alias = tmp_path / "alias"
    alias.symlink_to(config.parent, target_is_directory=True)
    payload = json.loads(config.read_text())
    payload["credential"] = str(alias / "secrets" / token.name)
    config.write_text(json.dumps(payload))
    original = config.read_bytes()
    with isolated_machine_home(
        {"YOKE_MACHINE_HOME": str(alias), "YOKE_SESSION_ID": "fixture"}
    ) as child:
        target = Path(child["YOKE_MACHINE_HOME"])
        copied = json.loads((target / "config.json").read_text())
        assert copied["credential"] == str(target / "secrets" / token.name)
        assert copied["cache_dir"] == str(target / "cache")
        Path(copied["credential"]).write_text("private-write")
    assert config.read_bytes() == original
    assert token.read_text() == "fixture-token"


def test_watcher_evidence_outlives_disposable_machine_settings(tmp_path):
    config, original, _ = _seed(tmp_path / "machine")
    with isolated_machine_home(
        {"YOKE_MACHINE_HOME": str(config.parent), "YOKE_SESSION_ID": "fixture"}
    ) as child:
        home = Path(child["YOKE_MACHINE_HOME"])
        evidence = Path(child["YOKE_SCRATCH_ROOT"])
        assert not evidence.is_relative_to(home)
        capture = evidence / "capture.log"
        capture.write_text("fixture proof")
    assert not home.exists()
    assert capture.read_text() == "fixture proof"
    assert config.read_bytes() == original
    capture.unlink()
    evidence.rmdir()
