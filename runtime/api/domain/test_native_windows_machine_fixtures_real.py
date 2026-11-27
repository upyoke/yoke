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
from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
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


def test_proxy_undo_removes_only_the_owned_thumbprint_and_seals_residue(lab, capsys):
    directory, context = lab
    conf = fixtures.FIXTURE_ROOT + r"\conf"
    seeded = _powershell(
        f"""$ErrorActionPreference='Stop'
$conf='{conf}'
New-Item -ItemType Directory -Force $conf | Out-Null
$owned=New-SelfSignedCertificate -Type Custom -Subject 'O=mitmproxy, CN=mitmproxy' -CertStoreLocation Cert:\\CurrentUser\\My
$other=New-SelfSignedCertificate -Type Custom -Subject 'CN=mitmproxy, O=mitmproxy' -CertStoreLocation Cert:\\CurrentUser\\My
$ownedFile=Join-Path $conf 'mitmproxy-ca-cert.cer'
$otherFile=Join-Path '{directory}' 'unattributed.cer'
Export-Certificate -Cert $owned -FilePath $ownedFile | Out-Null
Export-Certificate -Cert $other -FilePath $otherFile | Out-Null
Import-Certificate -FilePath $ownedFile -CertStoreLocation Cert:\\LocalMachine\\Root | Out-Null
Import-Certificate -FilePath $otherFile -CertStoreLocation Cert:\\LocalMachine\\CA | Out-Null
@{{owned=$owned.Thumbprint;other=$other.Thumbprint}} | ConvertTo-Json -Compress
""",
        directory,
    )
    assert seeded.returncode == 0, seeded.stderr
    thumbprints = json.loads(seeded.stdout)
    owned = thumbprints["owned"]
    other = thumbprints["other"]
    try:
        before = probe.observe(probe.gather_script())
        assert before is not None
        assert "fixture_root_ca_trusted" in probe.drift(before)
        undo_script = fixtures.fixture_script(context, "system-proxy-root-ca", "undo")
        for _ in range(2):
            undo = _powershell(undo_script, directory)
            records = verify_records(undo.stdout)
            assert undo.returncode == 1 and len(records) == 1, (undo.stdout, undo.stderr)
            record = records[0]
            assert not record["ok"]
            assert record["error"].startswith("proxy_fixture_not_undone")
            assert other in record["error"] and owned not in record["error"]
            assert not Path(conf).exists()
            assert probe.main(probe.gather_script(), PROBE_EXIT_CODES) == 25
            assert "fixture_root_ca_trusted" in json.loads(capsys.readouterr().out)["drift"]
        remaining = _powershell(
            f"(Test-Path -LiteralPath 'Cert:\\LocalMachine\\Root\\{owned}');"
            f"(Test-Path -LiteralPath 'Cert:\\LocalMachine\\CA\\{other}')",
            directory,
        )
        assert remaining.stdout.split() == ["False", "True"]
    finally:
        cleanup = _powershell(
            f"Remove-Item -LiteralPath 'Cert:\\LocalMachine\\Root\\{owned}',"
            f"'Cert:\\LocalMachine\\CA\\{other}',"
            f"'Cert:\\CurrentUser\\My\\{owned}','Cert:\\CurrentUser\\My\\{other}' "
            "-Force -ErrorAction SilentlyContinue",
            directory,
        )
        assert cleanup.returncode == 0, cleanup.stderr
    assert _run(lab, "system-proxy-root-ca", "undo")["state"]["unattributed_ca"] == []


def test_proxy_setup_verifies_the_actual_certificate_and_undo_removes_it(lab):
    directory, _ = lab
    try:
        setup = _run(lab, "system-proxy-root-ca", "setup")["state"]
        assert setup["ca_trusted"] and len(setup["ca_thumbprint"]) == 40
        assert setup["listening"] and setup["winhttp"] and setup["wininet_machine"]
    finally:
        undo = _run(lab, "system-proxy-root-ca", "undo")["state"]
        assert undo["unattributed_ca"] == [] and not undo["ca_present"]
    thumbprint = setup["ca_thumbprint"]
    owned = _powershell(f"Test-Path -LiteralPath 'Cert:\\LocalMachine\\Root\\{thumbprint}'", directory)
    assert owned.returncode == 0 and owned.stdout.strip() == "False"
