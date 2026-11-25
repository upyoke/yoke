"""Machine fixtures run for real on the disposable, elevated GitHub Windows runner.

The lab runs these scripts as SYSTEM through Azure run-command; the runner's
elevated admin is the same authority without Azure. Nothing here may run on a
persistent host: it changes machine-wide policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from yoke_contracts.machine_fixture_verify import verify_records
from yoke_harness.native_windows import machine_baseline_probe as probe
from yoke_harness.native_windows import machine_fixtures as fixtures
from yoke_harness.native_windows.profile import HELPERS as PROFILE_HELPERS

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        os.environ.get("YOKE_NATIVE_WINDOWS_PROVISIONING") != "1",
        reason="changes machine-wide policy only on a disposable GitHub Windows runner",
    ),
]

ROUNDTRIP = ("task-scheduler-restricted", "grant-admin", "applocker")


def _powershell(script: str, directory: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    path = directory / (uuid4().hex + ".ps1")
    path.write_text(script, encoding="utf-8")
    return subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    assert os.name == "nt" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    directory = tmp_path_factory.mktemp("fixtures")
    user = "yq" + uuid4().hex[:12]
    created = _powershell(
        PROFILE_HELPERS
        + f"""$ErrorActionPreference='Stop'
$secure=ConvertTo-SecureString ([Guid]::NewGuid().ToString('N')+'aA1!') -AsPlainText -Force
$account=New-LocalUser -Name '{user}' -Password $secure -PasswordNeverExpires
$null=Initialize-YokeProfile $account.SID.Value '{user}'
""",
        directory,
    )
    assert created.returncode == 0, created.stderr
    golden = directory / "golden"
    golden.mkdir()
    Path(str(golden) + ".probes").write_text(
        json.dumps({"probes": [{"name": "x", "argv": [sys.executable, "-c", "pass"]}]}), encoding="utf-8"
    )
    key = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(directory / "key")],
        capture_output=True, text=True, timeout=30,
    )
    assert key.returncode == 0, key.stderr
    public = (directory / "key.pub").read_text(encoding="utf-8").strip()
    return directory, fixtures.FixtureContext(user, str(golden), public)


def _run(lab, name, operation):
    directory, context = lab
    result = _powershell(fixtures.fixture_script(context, name, operation), directory)
    records = verify_records(result.stdout)
    assert result.returncode == 0 and len(records) == 1 and records[0]["ok"], (result.stdout, result.stderr)
    return records[0]


def test_every_script_parses_with_the_powershell_ast(lab):
    directory, context = lab
    scripts = {
        f"{name}-{operation}": fixtures.fixture_script(context, name, operation)
        for name in fixtures.FIXTURES
        for operation in ("setup", "undo")
    }
    scripts["undo-all"] = fixtures.undo_all_script(context)
    scripts["machine-baseline"] = probe.gather_script()
    for label, script in scripts.items():
        path = directory / f"{label}.ps1"
        path.write_text(script, encoding="utf-8")
        parsed = _powershell(
            "$errors=$null; $null=[Management.Automation.Language.Parser]::ParseFile("
            f"'{path}',[ref]$null,[ref]$errors); "
            "if($errors.Count){$errors | ForEach-Object {[Console]::Error.WriteLine($_.Message)}; exit 1}",
            directory,
            timeout=60,
        )
        assert parsed.returncode == 0, (label, parsed.stderr)


def test_second_user_setup_is_idempotent(lab):
    assert _run(lab, "second-user", "setup") == _run(lab, "second-user", "setup")


@pytest.mark.parametrize("name", ROUNDTRIP)
def test_setup_setup_undo_undo_leaves_identical_records(lab, name):
    assert _run(lab, name, "setup") == _run(lab, name, "setup")
    assert _run(lab, name, "undo") == _run(lab, name, "undo")


def test_machine_baseline_passes_after_the_roundtrips(lab):
    directory, _ = lab
    _run(lab, "second-user", "setup")
    for name in ROUNDTRIP:
        _run(lab, name, "undo")
    observed = probe.observe(probe.gather_script())
    assert observed is not None
    # The runner's own account is an administrator; the lab's test user is not
    # (the grant-admin undo record proves that above).
    assert [d for d in probe.drift(observed) if d != "test_user_administrator"] == [], observed
