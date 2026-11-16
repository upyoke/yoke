"""Exercise the production local engine on native CI runners, without a control plane."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from yoke_contracts.owner_private_path import create_owner_private_directory
from yoke_core.domain import local_universe, postgres_binaries, postgres_cluster


def _second_user_denied(spec: postgres_cluster.ClusterSpec) -> None:
    """Run a real libpq client as a second unprivileged Windows account."""
    public = Path(tempfile.mkdtemp(prefix="yoke-isolation-", dir="C:/Users/Public"))
    engine = public / "engine"
    shutil.copytree(spec.bin_dir.parent, engine)
    subprocess.run(["icacls", str(public), "/grant", "*S-1-5-32-545:(OI)(CI)RX", "/T", "/Q"], check=True)
    username = "yokeprobe" + secrets.token_hex(3)
    password = secrets.token_urlsafe(24) + "aA1!"
    env = {**os.environ, "YOKE_PROBE_USER": username, "YOKE_PROBE_PASSWORD": password,
           "YOKE_PROBE_ENGINE": str(engine / "bin"), "YOKE_PROBE_OUTPUT": str(public),
           "YOKE_PROBE_HOST": spec.socket_host, "YOKE_PROBE_DBUSER": spec.superuser}
    # Never put the generated account password on argv or in the log.
    script = r'''
$ErrorActionPreference = 'Stop'
$pass = ConvertTo-SecureString $env:YOKE_PROBE_PASSWORD -AsPlainText -Force
$user = $env:YOKE_PROBE_USER
New-LocalUser -Name $user -Password $pass | Out-Null
try {
    $cred = [pscredential]::new("$env:COMPUTERNAME\$user", $pass)
    $exe = Join-Path $env:YOKE_PROBE_ENGINE 'psql.exe'
    $out = Join-Path $env:YOKE_PROBE_OUTPUT 'client.out'
    $err = Join-Path $env:YOKE_PROBE_OUTPUT 'client.err'
    $version = Start-Process -FilePath $exe -ArgumentList '--version' -Credential $cred -WorkingDirectory $env:PUBLIC -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    if ($version.ExitCode -ne 0) { throw 'second_user_client_unavailable: positive execution control failed' }
    $args = '-h "' + $env:YOKE_PROBE_HOST + '" -U ' + $env:YOKE_PROBE_DBUSER + ' -d postgres -w -Atc "SELECT 1"'
    $probe = Start-Process -FilePath $exe -ArgumentList $args -Credential $cred -WorkingDirectory $env:PUBLIC -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $errorText = Get-Content -Raw $err
    if ($probe.ExitCode -eq 0) { throw 'owner_isolation_failed: second user connected' }
    if ($errorText -notmatch 'Permission denied|access|No such file|could not connect') { throw "second_user_refusal_undiagnosed: $errorText" }
    Write-Output 'SECOND_USER_CONNECTION_REFUSED'
} finally { Remove-LocalUser -Name $user }
'''
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True, timeout=120)


def verify() -> None:
    work = create_owner_private_directory(
        Path(tempfile.gettempdir()) / ("Yoke profile with spaces " + secrets.token_hex(8))
    )
    home = create_owner_private_directory(work / "machine home")
    os.environ["YOKE_MACHINE_HOME"] = str(home)
    os.environ.pop("YOKE_MACHINE_CONFIG_FILE", None)
    binary = postgres_binaries.ensure_binaries(emit=print)
    os.environ[postgres_binaries.BIN_DIR_ENV] = str(binary)
    # Standalone pg_dump/restore and the impersonated client need bundled DLLs too.
    os.environ["PATH"] = os.pathsep.join([str(binary), str(binary / "DLLs"), os.environ["PATH"]])
    spec = local_universe.cluster_spec(bin_dir=binary)
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        assert postgres_cluster.ensure_started(spec) == 0
        assert postgres_cluster.psql(spec, "SELECT 1").stdout.strip() == "1"
        assert postgres_cluster.psql(spec, "SHOW listen_addresses").stdout.strip() == ""
        assert postgres_cluster.stop(spec) == 0
        assert not postgres_cluster.is_ready(spec)
        assert postgres_cluster.ensure_started(spec) == 0
        assert postgres_cluster.stop(spec) == 0
        # PostgreSQL owns safe stale-lock recovery; never unlink a live server's lock.
        (spec.data_dir / "postmaster.pid").write_text(
            f"2147483647\n{spec.data_dir}\n0\n5432\n{spec.socket_host}\n", encoding="utf-8",
        )
        assert postgres_cluster.ensure_started(spec) == 0
        if os.name == "nt":
            _second_user_denied(spec)
        result = local_universe.birth(org_name="local-ci", admin_name="CI owner", emit=print)
        assert result["verified"]
        from yoke_core.domain import universe_export, universe_archive_validation
        archive = universe_export.export_universe(dsn=local_universe.local_dsn(spec), out=work / "universe.tar")
        assert postgres_cluster.psql(spec, "CREATE DATABASE restored").returncode == 0
        report = universe_archive_validation.validate_archive_roundtrip(
            Path(archive["artifact"]), postgres_cluster.dsn(spec, "restored"),
        )
        assert report["roundtrip"] and report["receipt_verified"]
        print(json.dumps({"lifecycle": "passed", "stale_lock_recovery": "passed",
                          "transport": "owner-private Unix socket", "roundtrip": "passed"}))
    finally:
        postgres_cluster.destroy(spec)


if __name__ == "__main__":
    verify()
