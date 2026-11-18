"""YOK-5407/YOK-5418: the disposable candidate controller runtime."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from yoke_core.domain.relay_release_path import relay_venv_executable, relay_venv_python
from yoke_core.tools import qa_controller_runtime as runtime_mod
from yoke_core.tools.qa_controller_runtime import (
    HANDOFF_MODULE,
    ControllerRuntimeError,
    ensure_controller_runtime,
)

COMMIT = "0de5f95e60de2a5231be4d8940a2d292764168fe"
VERSION = "0.2.0.202611171947"
BASE = "https://api.stage.example.test"


@pytest.fixture(autouse=True)
def machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _fake_install(*, version=VERSION, commit=COMMIT, handoff=True, calls=None):
    """A runner that builds a venv holding one yoke-core distribution."""

    def runner(argv, **kwargs):
        if calls is not None:
            calls.append(list(argv))
        if argv[1:4] == ["-I", "-m", "venv"]:
            root = Path(argv[-1])
            for executable in (relay_venv_python(root), relay_venv_executable(root)):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        root = Path(argv[0]).parent.parent
        info = runtime_mod._site_packages(root)[0] / f"yoke_core-{version}.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Name: yoke-core\nVersion: {version}\n", encoding="utf-8")
        (info / "scm_version.json").write_text(json.dumps({"node": f"g{commit}"}), encoding="utf-8")
        module = HANDOFF_MODULE.replace(".", "/") + ".py"
        (info.parent / module).parent.mkdir(parents=True)
        (info.parent / module).write_text("", encoding="utf-8")
        (info / "RECORD").write_text(
            f"{module},,\n" if handoff else "yoke_core/__init__.py,,\n", encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    return runner


def test_installs_candidate_wheels_isolated_from_the_installed_cli(machine_home):
    calls = []
    runtime = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT,
        runner=_fake_install(calls=calls),
    )
    assert runtime.root.parent == machine_home / "qa-controller-runtimes"
    assert runtime.root.name.startswith(f"{VERSION}-{COMMIT[:12]}-")
    assert runtime.executable == relay_venv_executable(runtime.root)
    pip = calls[1]
    assert pip[1:6] == ["-I", "-m", "pip", "--isolated", "install"]
    assert f"{BASE}/dist/releases/{VERSION}/wheels/yoke_core-{VERSION}-py3-none-any.whl" in pip
    # Nothing but a venv and pip ran: no installer, channel or settings change.
    assert len(calls) == 2
    receipt = json.loads((runtime.root / "controller-runtime.json").read_text(encoding="utf-8"))
    assert receipt["source_commit"] == COMMIT


def test_verified_runtime_is_reused_without_reinstalling():
    ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT, runner=_fake_install()
    )
    reused = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT,
        runner=lambda *a, **k: pytest.fail("reinstalled a verified runtime"),
    )
    assert reused.source_commit == COMMIT


def test_wheel_built_from_another_commit_is_refused(machine_home):
    with pytest.raises(ControllerRuntimeError, match="built from 111111111111"):
        ensure_controller_runtime(
            base_url=BASE, version=VERSION, source_commit=COMMIT,
            runner=_fake_install(commit="1" * 40),
        )
    parent = machine_home / "qa-controller-runtimes"
    assert [p.name for p in parent.iterdir() if not p.name.startswith(".")] == []


def test_release_without_the_handoff_module_is_refused():
    with pytest.raises(ControllerRuntimeError, match="predates the candidate-controller"):
        ensure_controller_runtime(
            base_url=BASE, version=VERSION, source_commit=COMMIT,
            runner=_fake_install(handoff=False),
        )


def test_failed_install_names_the_origin():
    def runner(argv, **kwargs):
        if "venv" in argv:
            return _fake_install()(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 1, "", "HTTP error 404")

    with pytest.raises(ControllerRuntimeError, match=f"wheels from {BASE}: HTTP error 404"):
        ensure_controller_runtime(
            base_url=BASE, version=VERSION, source_commit=COMMIT, runner=runner
        )


def test_least_recently_used_runtimes_are_pruned(machine_home):
    parent = machine_home / "qa-controller-runtimes"
    for index in range(5):
        (parent / f"old-{index}").mkdir(parents=True)
    runtime = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT, runner=_fake_install()
    )
    kept = [p for p in parent.iterdir() if not p.name.startswith(".")]
    assert len(kept) == runtime_mod.RETAINED_RUNTIMES
    assert runtime.root in kept


def test_runtime_installs_in_place_so_its_yoke_script_runs():
    """A venv moved after install keeps a shebang naming its old path."""
    calls = []
    runtime = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT,
        runner=_fake_install(calls=calls),
    )
    assert calls[0][-1] == str(runtime.root)
    runtime.executable.write_text("#!/elsewhere/.install-x/bin/python\n", encoding="utf-8")
    reinstalled = []
    fresh = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT,
        runner=_fake_install(calls=reinstalled),
    )
    assert reinstalled, "a runtime whose yoke launches a foreign interpreter is reinstalled"
    assert fresh.root != runtime.root and reinstalled[0][-1] == str(fresh.root)


def test_broken_runtime_in_use_is_kept_until_retention_drops_it(machine_home):
    """A controller handed off to runtime A keeps importing from it."""
    in_use = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT, runner=_fake_install()
    )
    module = runtime_mod._site_packages(in_use.root)[0] / (HANDOFF_MODULE.replace(".", "/") + ".py")
    in_use.executable.write_text("#!/elsewhere/bin/python\n", encoding="utf-8")
    replacement = ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit=COMMIT, runner=_fake_install()
    )
    assert replacement.root != in_use.root
    assert module.is_file() and in_use.python.is_file(), "the in-use runtime was deleted"
    for _ in range(runtime_mod.RETAINED_RUNTIMES - 2):
        ensure_controller_runtime(
            base_url=BASE, version=VERSION, source_commit="2" * 40,
            runner=_fake_install(commit="2" * 40),
        )
        assert in_use.root.exists()
    ensure_controller_runtime(
        base_url=BASE, version=VERSION, source_commit="3" * 40,
        runner=_fake_install(commit="3" * 40),
    )
    assert not in_use.root.exists(), "retention prunes the broken runtime once it ages out"


def test_concurrent_ensures_share_one_runtime_and_delete_nothing(machine_home):
    installs = []
    gate = threading.Barrier(2)

    def ensure(results):
        gate.wait()
        results.append(
            ensure_controller_runtime(
                base_url=BASE, version=VERSION, source_commit=COMMIT,
                runner=_fake_install(calls=installs),
            )
        )

    results = []
    threads = [threading.Thread(target=ensure, args=(results,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2 and results[0].root == results[1].root
    assert len(installs) == 2, "one venv and one pip install: a single runtime was built"
    assert not runtime_mod.verify_runtime(results[0].root, VERSION, COMMIT)
