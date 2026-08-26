"""The launchd boundary keeps automated tests out of the real login domain."""

from __future__ import annotations

import json
from pathlib import Path
import plistlib
import subprocess
import sys
from types import SimpleNamespace

import pytest
from _pytest.outcomes import Failed

from yoke_core.tools import launchctl_boundary as boundary


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sandbox = tmp_path / "launchd-sandbox"
    monkeypatch.setenv(boundary.SANDBOX_ENV, str(sandbox))
    return sandbox


def test_a_test_process_without_a_sandbox_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(boundary.SANDBOX_ENV, raising=False)
    monkeypatch.delenv(boundary.REAL_LAUNCHD_OPT_IN_ENV, raising=False)

    with pytest.raises(boundary.LaunchdBoundaryError) as refusal:
        boundary.run_launchctl(["launchctl", "bootstrap", "gui/501", "/x.plist"])

    message = str(refusal.value)
    assert "may not run launchctl" in message
    assert "real_launchd_agent" in message


def test_sandboxed_commands_are_recorded_instead_of_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, monkeypatch)
    plist = tmp_path / "com.upyoke.relay.abc123.plist"
    plist.write_bytes(plistlib.dumps({"Label": "com.upyoke.relay.abc123"}))
    target = "gui/501/com.upyoke.relay.abc123"

    assert boundary.run_launchctl(["launchctl", "print", target]).returncode == 1
    boundary.run_launchctl(["launchctl", "bootstrap", "gui/501", str(plist)])
    assert boundary.run_launchctl(["launchctl", "print", target]).returncode == 0
    boundary.run_launchctl(["launchctl", "bootout", target])
    assert boundary.run_launchctl(["launchctl", "print", target]).returncode == 1

    journal = sandbox / boundary.JOURNAL_NAME
    verbs = [entry[1] for entry in boundary.recorded_commands(sandbox)]
    assert verbs == ["print", "bootstrap", "print", "bootout", "print"]
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[0])["command"][0]


def test_the_canonical_relay_is_refused_even_with_the_integration_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(boundary.SANDBOX_ENV, raising=False)
    monkeypatch.setenv(boundary.REAL_LAUNCHD_OPT_IN_ENV, "1")

    with pytest.raises(boundary.LaunchdBoundaryError) as refusal:
        boundary.run_launchctl(
            ["launchctl", "bootout", f"gui/501/{boundary.CANONICAL_RELAY_LABEL}"]
        )

    assert "serves the whole fleet" in str(refusal.value)
    assert "yoke relay install" in str(refusal.value)


def test_a_per_environment_label_is_not_mistaken_for_the_canonical_one() -> None:
    suffixed = f"{boundary.CANONICAL_RELAY_LABEL}.abc123"
    canonical_plist = f"/x/{boundary.CANONICAL_RELAY_PLIST_NAME}"

    assert not boundary.names_canonical_relay(
        ["launchctl", "bootout", f"gui/501/{suffixed}"]
    )
    assert not boundary.names_canonical_relay(
        ["launchctl", "bootstrap", "gui/501", f"/x/{suffixed}.plist"]
    )
    assert boundary.names_canonical_relay(
        ["launchctl", "bootstrap", "gui/501", canonical_plist]
    )


def test_only_the_operators_real_launch_agents_folder_is_redirected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, monkeypatch)

    assert boundary.launch_agents_dir(tmp_path) == tmp_path / "Library" / "LaunchAgents"
    assert boundary.launch_agents_dir(Path.home()) == sandbox / "LaunchAgents"


def test_writing_into_the_real_folder_without_a_sandbox_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(boundary.SANDBOX_ENV, raising=False)

    with pytest.raises(boundary.LaunchdBoundaryError) as refusal:
        boundary.launch_agents_dir()

    assert "may not write a launch-agent plist" in str(refusal.value)


def test_bootout_labels_unloads_every_registered_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = _sandbox(tmp_path, monkeypatch)

    boundary.bootout_labels(["com.upyoke.relay.aaa", "com.upyoke.relay.bbb"], uid=501)

    assert [entry[-1] for entry in boundary.recorded_commands(sandbox)] == [
        "gui/501/com.upyoke.relay.aaa",
        "gui/501/com.upyoke.relay.bbb",
    ]


def test_the_integration_fixture_requires_its_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sanctioned door stays greppable: no marker, no real domain."""
    import conftest

    fixture = conftest._real_launchd_agent
    request = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _n: None))

    with pytest.raises(Failed, match="launchd_integration"):
        next(fixture(request, monkeypatch))


def test_the_marked_integration_fixture_boots_out_what_it_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import conftest

    sandbox = _sandbox(tmp_path, monkeypatch)
    request = SimpleNamespace(
        node=SimpleNamespace(get_closest_marker=lambda _n: object())
    )
    generator = conftest._real_launchd_agent(request, monkeypatch)
    register = next(generator)
    register("com.upyoke.relay.abc123")
    # The opt-in hands the boundary the real domain; put the sandbox back so
    # this test records the teardown instead of running it.
    monkeypatch.setenv(boundary.SANDBOX_ENV, str(sandbox))

    with pytest.raises(StopIteration):
        next(generator)

    recorded = boundary.recorded_commands(sandbox)
    assert [entry[1] for entry in recorded] == ["bootout"]
    assert recorded[0][-1].endswith("com.upyoke.relay.abc123")


def test_a_child_process_installing_a_relay_lands_in_the_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression: the leak arrived through a spawned installer.

    The onboard apply path spawns the relay installer, so nothing the test
    monkeypatches reaches it. The child resolves the operator's real home,
    and every launchd effect it asks for — including the canonical bootout
    the installer performs on the way in — has to land in the sandbox the
    parent exported.
    """
    sandbox = _sandbox(tmp_path, monkeypatch)
    config = tmp_path / "home" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage",
                "connections": {
                    "stage": {
                        "transport": "https",
                        "prod": False,
                        "api_url": "https://stage.example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": "~/.yoke/secrets/stage.token",
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    launcher = tmp_path / "bin" / "yoke"
    launcher.parent.mkdir()
    launcher.touch()
    program = (
        "from pathlib import Path\n"
        "from yoke_core.tools.session_relay_plist import install_relay_launchd\n"
        "status = install_relay_launchd(\n"
        f"    config_path={str(config)!r},\n"
        "    environment='stage',\n"
        f"    yoke_home=Path({str(tmp_path / 'home')!r}),\n"
        f"    executable=Path({str(launcher)!r}),\n"
        "    platform='darwin',\n"
        "    uid=501,\n"
        ")\n"
        "print(status.plist_path)\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    installed = Path(completed.stdout.strip())
    assert installed.parent == sandbox / "LaunchAgents"
    recorded = boundary.recorded_commands(sandbox)
    assert [entry[1] for entry in recorded] == [
        "bootout",
        "print",
        "bootout",
        "bootstrap",
        "print",
    ]
    assert recorded[0][-1].endswith(f"/{boundary.CANONICAL_RELAY_LABEL}")
