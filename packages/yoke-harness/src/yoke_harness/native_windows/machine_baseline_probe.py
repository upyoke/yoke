"""The native Windows ``machine-baseline`` standard probe: machine-wide drift.

The profile restore copies only the test user's files, so a leaked policy,
proxy, CA or group grant would poison every later case. Every reset runs
every fixture undo first; this probe seals what is left. It runs read-only as
the standard test user with the golden's sealed ``python.exe``, gathers the
facts in one PowerShell call, and fails ``probe_machine_drift`` naming each
drift. The checks are pure, so tests feed them captured observations.

Everything above the controller-side marker is sealed into goldens as the
probe program, so it imports only the standard library.
"""

import base64
import json
import subprocess
import sys


def drift(observed):
    """Every machine-wide drift in one gathered observation, as short names."""
    found = []
    if observed.get("srp_rules"):
        found.append("applocker_rules_present")
    if "direct access" not in str(observed.get("winhttp") or "").casefold():
        found.append("winhttp_proxy_set")
    if observed.get("hklm_proxy_enable"):
        found.append("wininet_machine_proxy_enabled")
    if observed.get("hkcu_proxy_enable"):
        found.append("wininet_user_proxy_enabled")
    if observed.get("proxy_per_user") is not None:
        found.append("proxy_settings_per_user_set")
    if observed.get("fixture_ca_present"):
        found.append("fixture_root_ca_trusted")
    if observed.get("mitmproxy_processes"):
        found.append("fixture_proxy_running")
    if observed.get("proxy_port_listening"):
        found.append("fixture_proxy_port_listening")
    if observed.get("fixture_entries"):
        found.append("fixture_files_present")
    if observed.get("task_policy"):
        found.append("task_scheduler_restricted")
    if observed.get("test_user_admin"):
        found.append("test_user_administrator")
    second = observed.get("second_user") or {}
    if not second.get("present"):
        found.append("second_user_missing")
    else:
        if second.get("disabled"):
            found.append("second_user_disabled")
        if second.get("admin"):
            found.append("second_user_administrator")
    return found


def observe(gather):
    """Run the gather script as this user; None when it returns no facts."""
    encoded = base64.b64encode(gather.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        observed = json.loads(result.stdout)
    except ValueError:
        return None
    return observed if result.returncode == 0 and isinstance(observed, dict) else None


def main(gather, exit_codes):
    observed = observe(gather)
    if observed is None:
        print(json.dumps({"drift": ["machine_facts_unreadable"]}))
        return exit_codes["probe_machine_drift"]
    found = drift(observed)
    if found:
        print(json.dumps({"drift": found}))
        return exit_codes["probe_machine_drift"]
    return 0


# --- controller side: not sealed into the probe program ---

PROBE_NAME = "machine-baseline"
_MARKER = "# --- controller side"


def gather_script():
    """Read-only facts for ``drift``; the fixture library names what to look for."""
    from yoke_harness.native_windows import machine_fixtures as fixtures
    from yoke_harness.native_windows.machine_fixture_accounts import CA_SUBJECT, PROXY_ADDRESS
    from yoke_harness.native_windows.machine_fixture_scripts import TASK_POLICY_KEY
    from yoke_harness.native_windows.powershell import quote

    port = PROXY_ADDRESS.rsplit(":", 1)[1]
    return f"""$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$o=[ordered]@{{}}
$srp='HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\SrpV2'
$o.srp_rules=if(Test-Path -LiteralPath $srp){{@(Get-ChildItem -LiteralPath $srp | ForEach-Object {{Get-ChildItem -LiteralPath $_.PSPath}}).Count}}else{{0}}
$o.winhttp=(& netsh.exe winhttp show proxy) -join ' '
$is='SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings'
$o.hklm_proxy_enable=(Get-ItemProperty -LiteralPath ('HKLM:\\'+$is) -ErrorAction SilentlyContinue).ProxyEnable
$o.hkcu_proxy_enable=(Get-ItemProperty -LiteralPath ('HKCU:\\'+$is) -ErrorAction SilentlyContinue).ProxyEnable
$o.proxy_per_user=(Get-ItemProperty -LiteralPath 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\CurrentVersion\\Internet Settings' -ErrorAction SilentlyContinue).ProxySettingsPerUser
$o.fixture_ca_present=[bool](@('Root','CA') | ForEach-Object {{Get-ChildItem ('Cert:\\LocalMachine\\'+$_)}} | Where-Object {{$_.Subject -eq {quote(CA_SUBJECT)}}})
$o.mitmproxy_processes=@(Get-Process mitmdump,mitmproxy,mitmweb -ErrorAction SilentlyContinue).Count
$o.proxy_port_listening=@([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object {{$_.Port -eq {port}}}).Count -gt 0
$o.fixture_entries=if(Test-Path -LiteralPath {quote(fixtures.FIXTURE_ROOT)}){{@(Get-ChildItem -LiteralPath {quote(fixtures.FIXTURE_ROOT)} -Force).Count}}else{{0}}
$o.task_policy=Test-Path -LiteralPath {quote(TASK_POLICY_KEY)}
function Get-YokeGroupSids([string]$groupSid){{
 $group=([Security.Principal.SecurityIdentifier]$groupSid).Translate([Security.Principal.NTAccount]).Value.Split('\\')[-1]
 @(([ADSI]"WinNT://./$group,group").Invoke('Members') | ForEach-Object {{
  ([Security.Principal.SecurityIdentifier]::new([byte[]]$_.GetType().InvokeMember('objectSid','GetProperty',$null,$_,$null),0)).Value
 }})
}}
$admins=Get-YokeGroupSids 'S-1-5-32-544'
$o.test_user_admin=$admins -contains [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$second=[ordered]@{{present=$false}}
try {{
 $account=[ADSI]('WinNT://./'+{fixtures.ps_text(fixtures.SECOND_USER)}+',user')
 $sid=([Security.Principal.SecurityIdentifier]::new([byte[]]$account.objectSid.Value,0)).Value
 $second=[ordered]@{{present=$true;disabled=[bool]($account.UserFlags.Value -band 2);admin=($admins -contains $sid)}}
}} catch {{}}
$o.second_user=$second
$o | ConvertTo-Json -Compress -Depth 4
"""


def probe_program():
    """The sealed program: the checks above, then a call with today's gather."""
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    sealed = source[: source.index(_MARKER)]
    return sealed + f"\nsys.exit(main({gather_script()!r}, EXIT))\n"


__all__ = ["PROBE_NAME", "drift", "gather_script", "main", "observe", "probe_program"]
