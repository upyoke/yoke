"""A relay release is ready only when the stable launcher can load it.

These tests run real interpreters against real release trees built under
``tmp_path``, never the developer checkout, so an ambient ``PYTHONPATH`` or an
editable install cannot stand in for a package the release is missing. Each
case pairs the readiness verdict with what the stable launcher itself does on
the same tree: the two must agree, because the verdict exists to predict the
launcher.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from yoke_core.tools.session_relay_package_validate import (
    RELAY_PACKAGE_PROBE_TIMEOUT_SECONDS,
    relay_package_runnable_reason,
)
from yoke_core.tools.session_relay_release import (
    PYTHON_ISOLATION_FLAG,
    RELAY_RELEASE_INSTALL_FAILED,
    relay_release_status,
    relay_runtime_python,
    write_release_json,
)
from yoke_core.tools.session_relay_runtime_install import ensure_relay_runtime


RELEASE = "0.1.1+launch.365"
OTHER_RELEASE = "0.1.1+launch.300"

# The pointer pair pip writes for an editable install. Setuptools appends its
# finder to sys.meta_path, so it only answers for a package no directory on
# sys.path holds -- which is exactly the state a release is left in when an
# editable install replaces its packages.
_EDITABLE_FINDER = """
import sys
from importlib.util import spec_from_file_location

MAPPING = {mapping!r}


class _EditableFinder:
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        location = MAPPING.get(fullname)
        if location is None:
            return None
        return spec_from_file_location(
            fullname,
            f"{{location}}/__init__.py",
            submodule_search_locations=[location],
        )


def install():
    if _EditableFinder not in sys.meta_path:
        sys.meta_path.append(_EditableFinder)
"""


def _site_packages(prefix: Path) -> Path:
    return (
        prefix
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )


def _write_yoke_cli(packages: Path, release: str) -> Path:
    """An importable yoke_cli beside the yoke-core metadata that names it."""
    dist_info = packages / f"yoke_core-{release}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: yoke-core\nVersion: {release}\n",
        encoding="utf-8",
    )
    cli = packages / "yoke_cli"
    cli.mkdir(parents=True, exist_ok=True)
    (cli / "__init__.py").write_text("", encoding="utf-8")
    (cli / "main.py").write_text(
        "def main(_argv):\n    print(__file__)\n    return 0\n",
        encoding="utf-8",
    )
    return cli


def _write_editable_pointer(packages: Path, target: Path) -> None:
    """Leave behind what an editable install leaves: pointers, not a package."""
    packages.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(packages / "yoke_cli", ignore_errors=True)
    (packages / "__editable___yoke_cli_finder.py").write_text(
        _EDITABLE_FINDER.format(mapping={"yoke_cli": str(target)}),
        encoding="utf-8",
    )
    (packages / "__editable__.yoke_cli.pth").write_text(
        "import __editable___yoke_cli_finder; __editable___yoke_cli_finder.install()\n",
        encoding="utf-8",
    )


def _pinned_relay(tmp_path: Path, release: str = RELEASE):
    """A state dir holding the stable runtime and one active release tree."""
    instance = relay_instance(tmp_path)
    instance.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_relay_runtime(instance.state_dir)
    active = instance.state_dir / "releases" / "active"
    _write_yoke_cli(_site_packages(active), release)
    (active / "bin").mkdir(parents=True, exist_ok=True)
    (active / "bin" / "python").touch()
    (active / "bin" / "yoke").touch()
    write_release_json(
        active / ".yoke-relay-release.json",
        {
            "schema": 1,
            "pinned_release": release,
            "served_build": f"v{release}",
            "distribution_index": "https://relay.example.test/simple/",
        },
    )
    (instance.state_dir / "release").symlink_to(active, target_is_directory=True)
    return instance, active


def _start_the_launcher(state_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the stable launcher exactly as launchd runs it."""
    return subprocess.run(
        [str(state_dir / "runtime" / "bin" / "yoke")],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def test_an_intact_release_is_ready_and_the_launcher_starts_on_it(
    tmp_path: Path,
) -> None:
    instance, active = _pinned_relay(tmp_path)

    status = relay_release_status(
        instance=instance, refresh_served=False, fetch_manifest=lambda _env: None
    )
    started = _start_the_launcher(instance.state_dir)

    assert status.package_ready
    assert not status.error_code
    assert started.returncode == 0, started.stderr
    assert Path(started.stdout.strip()).is_relative_to(active)


def test_a_release_replaced_by_editable_pointers_is_not_ready(tmp_path: Path) -> None:
    """The incident shape: the receipt still matches, the package is gone.

    A sys.path entry is not a site directory, so the ``.pth`` left behind is
    never even executed -- the release simply has no yoke_cli to import, and
    the launcher fails on exactly the import the readiness probe performs.
    """
    instance, active = _pinned_relay(tmp_path)
    _write_editable_pointer(
        _site_packages(active), tmp_path / "a-worktree-that-moved" / "yoke_cli"
    )

    status = relay_release_status(
        instance=instance, refresh_served=False, fetch_manifest=lambda _env: None
    )
    started = _start_the_launcher(instance.state_dir)

    assert not status.package_ready
    assert not status.current
    assert status.error_code == RELAY_RELEASE_INSTALL_FAILED
    assert "ModuleNotFoundError" in status.error_message
    assert started.returncode == 1
    assert "relay_runtime_start_failed" in started.stderr


def test_a_release_whose_package_comes_from_elsewhere_is_not_ready(
    tmp_path: Path,
) -> None:
    """An editable pointer that still resolves is the quieter failure.

    The stable runtime's own site-packages is a real site directory, so its
    editable pointer runs and answers for the package the release no longer
    holds. The launcher starts -- on a checkout nobody released -- and only
    the origin the probe checks distinguishes that from a healthy release.
    """
    instance, active = _pinned_relay(tmp_path)
    foreign = tmp_path / "a-live-worktree"
    _write_yoke_cli(foreign, OTHER_RELEASE)
    _write_editable_pointer(_site_packages(active), foreign / "yoke_cli")
    _write_editable_pointer(
        _site_packages(instance.state_dir / "runtime"), foreign / "yoke_cli"
    )

    reason = relay_package_runnable_reason(
        relay_runtime_python(instance.state_dir),
        instance.state_dir / "release",
        RELEASE,
        isolation_flag=PYTHON_ISOLATION_FLAG,
    )
    started = _start_the_launcher(instance.state_dir)

    assert "outside the release" in reason
    assert str(foreign) in reason
    assert started.returncode == 0, started.stderr
    assert Path(started.stdout.strip()).is_relative_to(foreign)
    assert not Path(started.stdout.strip()).is_relative_to(active)


def test_a_release_reporting_another_version_is_not_ready(tmp_path: Path) -> None:
    instance, _active = _pinned_relay(tmp_path, OTHER_RELEASE)

    reason = relay_package_runnable_reason(
        relay_runtime_python(instance.state_dir),
        instance.state_dir / "release",
        RELEASE,
        isolation_flag=PYTHON_ISOLATION_FLAG,
    )

    assert OTHER_RELEASE in reason
    assert RELEASE in reason


def test_a_wedged_probe_is_bounded_and_names_its_timeout(tmp_path: Path) -> None:
    instance, _active = _pinned_relay(tmp_path)

    def hang(command, **kwargs):
        assert kwargs["timeout"] == RELAY_PACKAGE_PROBE_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(list(command), kwargs["timeout"])

    reason = relay_package_runnable_reason(
        relay_runtime_python(instance.state_dir),
        instance.state_dir / "release",
        RELEASE,
        isolation_flag=PYTHON_ISOLATION_FLAG,
        runner=hang,
    )

    assert "did not finish within" in reason
    assert "wedged" in reason


def test_a_missing_stable_interpreter_is_named_without_spawning(
    tmp_path: Path,
) -> None:
    def unreachable(command, **_kwargs):
        raise AssertionError(f"probed a missing interpreter: {command}")

    reason = relay_package_runnable_reason(
        tmp_path / "runtime" / "bin" / "python",
        tmp_path / "release",
        RELEASE,
        isolation_flag=PYTHON_ISOLATION_FLAG,
        runner=unreachable,
    )

    assert "stable relay interpreter is missing" in reason


@pytest.mark.parametrize("absent", ("the release", "its packages"))
def test_an_absent_release_tree_is_named_rather_than_raised(
    tmp_path: Path, absent: str
) -> None:
    instance, active = _pinned_relay(tmp_path)
    if absent == "the release":
        (instance.state_dir / "release").unlink()
    else:
        shutil.rmtree(_site_packages(active))

    reason = relay_package_runnable_reason(
        relay_runtime_python(instance.state_dir),
        instance.state_dir / "release",
        RELEASE,
        isolation_flag=PYTHON_ISOLATION_FLAG,
    )

    assert "Traceback" not in reason
    assert "is missing at" in reason or "holds no packages" in reason
