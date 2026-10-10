"""Real temporary artifacts and early host-capacity refusals."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import test_machine_temp_script as program
from yoke_harness.ssh_mac_baseline_probes import reach_user_equivalent_baseline
from yoke_harness.test_machine_types import HostActionResult
from yoke_core.domain.agent_mission_preparation import prepare_mission


def test_cleanup_removes_run_artifacts_preserving_golden_home_and_other_users(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "temp"
    home.mkdir()
    root.mkdir()
    golden = root / "yoke-golden" / "sealed"
    golden.mkdir(parents=True)
    (golden / "home.tar.gz").write_text("golden")
    protected = root / "playwright-baseline"
    protected.mkdir()
    home_temp = home / "yoke-candidate"
    home_temp.mkdir()
    for name in (
        "yoke-real-harness-old",
        "yoke-relay-candidate-old",
        "yoke-setup-candidate-old",
        "playwright_chromium_profile-old",
        "pip-unpack-old",
    ):
        candidate = root / name
        candidate.mkdir()
        (candidate / "data").write_bytes(b"x" * 65536)
    unrelated = root / "unrelated"
    unrelated.write_text("keep")
    link = root / "yoke-link"
    link.symlink_to(golden, target_is_directory=True)
    receipt = program.cleanup([root, home], [home, golden, protected])
    assert receipt["ok"] and receipt["removed_entries"] == 6
    assert receipt["freed_bytes"] >= 0
    assert (golden / "home.tar.gz").read_text() == "golden"
    assert protected.is_dir() and home_temp.is_dir() and unrelated.exists()
    assert not link.exists()
    assert {p.name for p in root.iterdir()} == {
        "yoke-golden",
        "playwright-baseline",
        "unrelated",
    }


def test_foreign_owner_refuses_before_deleting_any_candidate(tmp_path, monkeypatch):
    candidate = tmp_path / "yoke-run"
    candidate.mkdir()
    (candidate / "data").write_text("owned")
    original = Path.lstat

    def foreign(path):
        result = original(path)
        return (
            SimpleNamespace(st_uid=result.st_uid + 1, st_dev=result.st_dev)
            if path.name == "data"
            else result
        )

    monkeypatch.setattr(Path, "lstat", foreign)
    with pytest.raises(ValueError, match="temp_ownership_refused"):
        program.cleanup([tmp_path], [])
    assert (candidate / "data").read_text() == "owned"


@pytest.mark.parametrize("os_name", ["macos", "linux", "windows"])
def test_shared_baseline_receipt_includes_cleanup_and_protects_declared_paths(os_name):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[3] == "cleanup"
        assert argv[4:] == [
            "/home/test",
            "/tmp/yoke-golden",
            "/tmp/yoke-golden.manifest",
            "/tmp/yoke-golden.probes",
        ]
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"ok": True, "freed_bytes": 99}), ""
        )

    control = SimpleNamespace(
        os=os_name,
        home="/home/test",
        golden_baseline_path="/tmp/yoke-golden",
        run_command=run,
        reset_installer_test_host=lambda: HostActionResult(True, {"restored": True}),
        prove_user_equivalent=lambda: HostActionResult(True, {"proven": True}),
    )
    result = reach_user_equivalent_baseline(control)
    assert result.ok and result.evidence["temp_cleanup"]["freed_bytes"] == 99
    assert len(calls) == 1


def test_low_disk_refuses_before_scratch_or_packages(tmp_path, monkeypatch):
    monkeypatch.setattr(
        program.shutil, "disk_usage", lambda path: SimpleNamespace(free=123)
    )
    receipt = program.disk_preflight([tmp_path], tmp_path)
    assert receipt["error_code"] == "test_machine_disk_space_low"
    assert receipt["minimum_free_bytes"] == program.MINIMUM_MISSION_FREE_BYTES
    control = SimpleNamespace(
        home=str(tmp_path),
        run_command=lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, json.dumps(receipt), ""
        ),
    )
    contract = SimpleNamespace(
        baselines=[],
        lease_id=1,
        plan_execution_id="mission",
        contract_digest="digest",
        cases=[SimpleNamespace(host_baseline=None, method_config={})],
    )
    preparation = prepare_mission(
        contract,
        execution_factory=lambda *args, **kwargs: SimpleNamespace(
            control=control, material=SimpleNamespace(secrets={})
        ),
        scratch_factory=lambda *args, **kwargs: pytest.fail(
            "scratch created below disk floor"
        ),
    )["preparation"]
    assert not preparation["ok"]
    assert preparation["error_code"] == "test_machine_disk_space_low"
    failure = preparation["evidence"]["preparation_failure"]
    assert failure["phase"] == "disk_preflight" and "reset" in failure["recovery"]
    assert preparation["evidence"]["scratch_created"] is False


def test_cleanup_failure_prevents_baseline_proof():
    control = SimpleNamespace(
        home="/home/test",
        golden_baseline_path="/golden/home",
        run_command=lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", ""),
        reset_installer_test_host=lambda: HostActionResult(True, {"restored": True}),
        prove_user_equivalent=lambda: pytest.fail("proof after failed cleanup"),
    )
    result = reach_user_equivalent_baseline(control)
    assert not result.ok
    assert result.error_code == "test_machine_temp_receipt_invalid"
    assert "reset" in result.evidence["temp_cleanup"]["recovery"]


def test_cleanup_preserves_live_mission_scratch_and_removes_stale_siblings(tmp_path):
    root = tmp_path / "yoke-qa-mission"
    live = root / "live"
    stale = root / "stale"
    live.mkdir(parents=True)
    stale.mkdir()
    (live / "evidence").write_text("keep")
    (stale / "candidate").write_text("remove")
    receipt = program.cleanup([tmp_path], [live])
    assert receipt["removed_entries"] == 1
    assert (live / "evidence").read_text() == "keep"
    assert not stale.exists()
