"""Commit-clock releases keep ordering, relay origin and exact product bytes."""

import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from yoke_contracts.engine_version import compare_engine_versions
from yoke_core.tools.session_relay_release import (
    RelayReleaseError,
    release_version_from_build,
)
from yoke_core.tools import local_wheel_constraints, session_relay_release_install


def test_commit_minutes_order_numerically():
    assert compare_engine_versions("0.2.0.202610140941", "0.2.0.202610140942") == -1
    assert compare_engine_versions("0.2.0.202610140941", "0.2.0.202610140941") == 0
    assert compare_engine_versions("0.2.0.202610150941", "0.2.0.202610140942") == 1


def test_relay_keeps_exact_canonical_handshake_version():
    assert release_version_from_build("0.2.0.202610140941") == "0.2.0.202610140941"


@pytest.mark.parametrize("value", ["source", "not-a-version", ""])
def test_relay_refuses_invalid_package_identity(value):
    with pytest.raises(RelayReleaseError, match="not a valid Yoke release version"):
        release_version_from_build(value)


def test_container_constraints_bind_actual_wheel_paths(tmp_path):
    wheel = tmp_path / "yoke_core-0.2.0.202610140941-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as out:
        out.writestr(
            "yoke_core.dist-info/METADATA",
            "Name: yoke-core\nVersion: 0.2.0.202610140941\n",
        )
    assert local_wheel_constraints.constraints_for_wheelhouse(
        tmp_path, ["yoke-core"]
    ) == [f"yoke-core @ {wheel.as_uri()}"]


def test_relay_install_binds_every_product_to_declared_origin(tmp_path):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "injected download refusal")

    with pytest.raises(RelayReleaseError, match="injected download refusal"):
        session_relay_release_install._install_candidate(
            SimpleNamespace(state_dir=tmp_path),
            release="0.2.0.202610140941",
            served_build="0.2.0.202610140941",
            index="https://packages.example.com/simple/",
            runtime_python=tmp_path / "runtime-python",
            create_venv=lambda path: path.mkdir(),
            runner=run,
        )
    products = [arg for arg in calls[0] if arg.startswith("https://")]
    assert set(products) == {
        "https://packages.example.com/dist/releases/0.2.0.202610140941/wheels/"
        f"yoke_{name}-0.2.0.202610140941-py3-none-any.whl"
        for name in ("contracts", "cli", "harness", "core")
    }
    assert "--extra-index-url" not in calls[0]


def test_public_relay_pin_preserves_the_numeric_handshake(tmp_path):
    from runtime.api.tools.session_relay_release_test_support import (
        fake_venv,
        relay_instance,
        runner_for,
    )

    version = "0.2.0.202610140941"
    calls = []

    def runtime(path):
        fake_venv(path)
        (path / "bin/python").chmod(0o700)

    status = session_relay_release_install.pin_relay_release(
        instance=relay_instance(tmp_path),
        served_build=version,
        create_venv=fake_venv,
        create_runtime=runtime,
        runner=runner_for(version, calls),
    )
    assert status.current
    assert status.served_build == status.pinned_release == version
    assert len([cmd for cmd in calls if "pip" in cmd]) == 1


def test_response_and_source_comparison_keep_exact_numeric_tag(monkeypatch):
    from yoke_cli.transport import https_engine_handshake as handshake

    version = "0.2.0.202610140941"
    observed, comparisons = [], []
    monkeypatch.setattr(handshake, "local_handshake_version", lambda: "")
    monkeypatch.setattr(handshake, "_loaded_source_checkout", lambda: "/source")
    monkeypatch.setattr(
        handshake.source_build_skew,
        "compare_to_server_build",
        lambda root, build: comparisons.append((root, build)),
    )
    monkeypatch.setattr(
        handshake.control_plane_payload,
        "observe_server_build",
        lambda build, comparison: observed.append(build),
    )
    state = handshake.ServerHandshake()
    handshake.observe_server_version({handshake.ENGINE_VERSION_HEADER: version}, state)
    assert state.engine_version == version
    assert observed == [version]
    assert comparisons == [("/source", version)]
