"""Physical identity coverage for the release-pinned standing relay."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_cli.config.session_relay_instance import resolve_relay_instance
from yoke_core.tools.session_relay_plist import (
    relay_launchd_paths,
    relay_plist_document,
)
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RelayReleaseError,
    write_release_json,
)
from yoke_core.tools.session_relay_release_install import pin_relay_release
from yoke_harness import session_relay_native_spawn
from yoke_harness.session_relay_environment import native_session_environment


FIRST_RELEASE = "0.1.1+launch.365"
SECOND_RELEASE = "0.1.1+launch.366"


def _instance(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "prod": True,
                        "api_url": "https://relay.example.test/api",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return resolve_relay_instance(
        config_path=config,
        environment="prod",
        yoke_home=tmp_path / "state",
    )


def _fake_release(path: Path, release: str) -> None:
    binary = path / "bin"
    binary.mkdir(parents=True)
    (binary / "python").touch()
    (binary / "yoke").touch()
    packages = (
        path
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    cli = packages / "yoke_cli"
    cli.mkdir(parents=True)
    (cli / "__init__.py").write_text("", encoding="utf-8")
    (cli / "main.py").write_text(
        "from pathlib import Path\n"
        "import json, os, sys\n"
        "def main(_argv):\n"
        f"    print(json.dumps({{'release': {release!r}, "
        "'pid': os.getpid(), 'executable': str(Path(sys.executable).resolve()), "
        "'pythonpath': os.environ.get('PYTHONPATH', '')}))\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (packages / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "probe = os.environ.get('STALE_STARTUP_PROBE')\n"
        f"if probe: Path(probe).write_text({release!r})\n",
        encoding="utf-8",
    )
    harness = packages / "yoke_harness"
    harness.mkdir()
    (harness / "__init__.py").write_text("", encoding="utf-8")
    (harness / "session_relay_native_supervisor.py").write_text(
        "from pathlib import Path\n"
        "import json, os, sys\n"
        "if __name__ == '__main__':\n"
        "    Path(os.environ['RELAY_CHILD_PROBE']).write_text(json.dumps({\n"
        f"        'release': {release!r}, 'module': __file__,\n"
        "        'executable': str(Path(sys.executable).resolve()),\n"
        "    }))\n",
        encoding="utf-8",
    )


def _runner_for(release: str):
    def run(command, **_kwargs):
        argv = list(command)
        stdout = f"{release}\n" if "-c" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    return run


def _start_from_plist(
    instance,
    tmp_path: Path,
    *,
    extra_environment: dict[str, str] | None = None,
) -> tuple[dict[str, object], dict]:
    document = relay_plist_document(
        paths=relay_launchd_paths(home=tmp_path, instance=instance),
        environ=os.environ,
    )
    environment = {
        **os.environ,
        **document["EnvironmentVariables"],
        **(extra_environment or {}),
    }
    completed = subprocess.run(
        document["ProgramArguments"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return document, json.loads(completed.stdout)


def test_failed_first_upgrade_keeps_the_existing_launch_target(
    tmp_path: Path,
) -> None:
    instance = _instance(tmp_path)
    prior_release = instance.state_dir / "releases" / "prior"
    _fake_release(prior_release, FIRST_RELEASE)
    write_release_json(
        prior_release / ".yoke-relay-release.json",
        {
            "schema": 1,
            "pinned_release": FIRST_RELEASE,
            "served_build": f"v{FIRST_RELEASE}",
            "distribution_index": "https://relay.example.test/simple/",
        },
    )
    (instance.state_dir / "venv").symlink_to(prior_release, target_is_directory=True)

    def fail_fetch(command, **_kwargs):
        argv = list(command)
        return subprocess.CompletedProcess(argv, 1, "", "index unavailable")

    with pytest.raises(RelayReleaseError) as raised:
        pin_relay_release(
            instance=instance,
            served_build=f"v{SECOND_RELEASE}",
            create_venv=lambda path: _fake_release(path, SECOND_RELEASE),
            runner=fail_fetch,
        )

    assert raised.value.code == RELAY_RELEASE_FETCH_FAILED
    assert (instance.state_dir / "runtime").is_dir()
    assert (instance.state_dir / "venv").resolve() == prior_release
    assert (instance.state_dir / "release").resolve() == prior_release


def test_release_updates_keep_one_runtime_and_supervised_children_on_the_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance(tmp_path)
    first = pin_relay_release(
        instance=instance,
        served_build=f"v{FIRST_RELEASE}",
        create_venv=lambda path: _fake_release(path, FIRST_RELEASE),
        runner=_runner_for(FIRST_RELEASE),
    )
    first_release_root = (instance.state_dir / "release").resolve()
    first_identity = first.runtime_python.stat()
    first_document, first_process = _start_from_plist(instance, tmp_path)

    second = pin_relay_release(
        instance=instance,
        served_build=f"v{SECOND_RELEASE}",
        create_venv=lambda path: _fake_release(path, SECOND_RELEASE),
        runner=_runner_for(SECOND_RELEASE),
    )
    second_release_root = (instance.state_dir / "release").resolve()
    second_identity = second.runtime_python.stat()
    stale_startup_probe = tmp_path / "stale-sitecustomize"
    second_document, second_process = _start_from_plist(
        instance,
        tmp_path,
        extra_environment={
            "PYTHONPATH": first_process["pythonpath"],
            "STALE_STARTUP_PROBE": str(stale_startup_probe),
        },
    )

    assert first_release_root != second_release_root
    assert first_document["ProgramArguments"] == second_document["ProgramArguments"]
    assert first_process["release"] == FIRST_RELEASE
    assert second_process["release"] == SECOND_RELEASE
    assert first_process["pid"] != second_process["pid"]
    assert first_process["executable"] == second_process["executable"]
    assert first_process["executable"] == str(second.runtime_python.resolve())
    assert not stale_startup_probe.exists()
    assert (first_identity.st_dev, first_identity.st_ino) == (
        second_identity.st_dev,
        second_identity.st_ino,
    )
    assert (instance.state_dir / "venv").is_symlink()
    assert (instance.state_dir / "venv").resolve() == instance.state_dir / "runtime"

    child_probe = tmp_path / "supervised-child.json"
    child_environment = native_session_environment(
        executor="cursor",
        environ={
            **os.environ,
            "PYTHONPATH": second_process["pythonpath"],
            "RELAY_CHILD_PROBE": str(child_probe),
        },
    )
    monkeypatch.setattr(
        session_relay_native_spawn,
        "record_supervised_native",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        session_relay_native_spawn,
        "sys",
        SimpleNamespace(executable=str(second.runtime_python)),
    )
    started = session_relay_native_spawn.spawn_supervised_native(
        ["/usr/bin/true"],
        checkout=tmp_path,
        environment=child_environment,
        attempt_id=str(uuid4()),
        native_session_id=None,
        binary_source="path",
        state_dir=tmp_path / "native-state",
    )

    assert started is not None
    _pid, wait_status = os.waitpid(started.pid, 0)
    assert os.waitstatus_to_exitcode(wait_status) == 0
    child = json.loads(child_probe.read_text(encoding="utf-8"))
    assert child["release"] == SECOND_RELEASE
    assert Path(child["module"]).resolve().is_relative_to(second_release_root)
    assert child["executable"] == str(second.runtime_python.resolve())
