"""Machine-wide native Windows QA fixtures: idempotent setup and undo pairs.

Each fixture is a pair of PowerShell bodies that run as SYSTEM through the
control's ``run_system_script`` (Azure run-command on the labs). Each checks
state, changes only what differs and prints one verify record. Every native
Windows reset runs every undo first, in ``UNDO_ORDER``, so no fixture
outlives the walk that applied it; the ``machine-baseline`` probe then seals
what the undo could miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_fixture_verify import (
    FIXTURE_FAILED,
    RUNNER_UNAVAILABLE,
    VERIFY_MARKER,
    MachineFixtureFailed,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows import machine_fixture_accounts as accounts
from yoke_harness.native_windows import machine_fixture_scripts as policies
from yoke_contracts.windows_powershell import quote

SECOND_USER = "Zoë Tester"
FIXTURE_ROOT = r"C:\YokeQa\fixtures"
SYSTEM_SCRIPT_TIMEOUT_SECONDS = 900

# name -> (setup, undo)
FIXTURES: dict[str, tuple[str, str]] = {
    "grant-admin": (policies.GRANT_ADMIN_SETUP, policies.GRANT_ADMIN_UNDO),
    "system-proxy-root-ca": (accounts.PROXY_SETUP, accounts.PROXY_UNDO),
    "applocker": (policies.applocker_setup(), policies.APPLOCKER_UNDO),
    "task-scheduler-restricted": (
        policies.TASK_SCHEDULER_SETUP,
        policies.TASK_SCHEDULER_UNDO,
    ),
    "second-user": (accounts.SECOND_USER_SETUP, accounts.SECOND_USER_UNDO),
}
# Task Scheduler leads: its policy blocks the reset's own task restore.
UNDO_ORDER = (
    "task-scheduler-restricted",
    "applocker",
    "system-proxy-root-ca",
    "grant-admin",
    "second-user",
)


def ps_text(value: str) -> str:
    """A PowerShell string expression that keeps non-ASCII text intact.

    Run-command and staged files may be read in the ANSI code page, so a
    literal like ``Zoë`` is built from ``[char]`` codes instead.
    """
    parts, run = [], ""
    for char in str(value):
        if char.isascii():
            run += char
            continue
        if run:
            parts.append(quote(run))
            run = ""
        parts.append(f"[string][char]0x{ord(char):04X}")
    if run or not parts:
        parts.append(quote(run))
    return "(" + "+".join(parts) + ")"


@dataclass(frozen=True)
class FixtureContext:
    test_user: str
    golden_baseline_path: str
    public_key: str


PRELUDE = r"""$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $ConfirmPreference='None'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$testUser=TEST_USER; $secondUser=SECOND_USER; $fixtureRoot=FIXTURE_ROOT
$golden=GOLDEN; $publicKey=PUBLIC_KEY
$script:fixtureFailed=$false
function Get-YokeUserSid([string]$user){
 ([Security.Principal.NTAccount]::new($user)).Translate([Security.Principal.SecurityIdentifier]).Value
}
# ADSI reads members by SID; Get-LocalGroupMember fails on orphaned members.
function Get-YokeGroupSids([string]$groupSid){
 $group=([Security.Principal.SecurityIdentifier]$groupSid).Translate([Security.Principal.NTAccount]).Value.Split('\')[-1]
 @(([ADSI]"WinNT://./$group,group").Invoke('Members') | ForEach-Object {
  $bytes=$_.GetType().InvokeMember('objectSid','GetProperty',$null,$_,$null)
  ([Security.Principal.SecurityIdentifier]::new([byte[]]$bytes,0)).Value
 })
}
"""


def _prelude(context: FixtureContext) -> str:
    values = {
        "TEST_USER": ps_text(context.test_user),
        "SECOND_USER": ps_text(SECOND_USER),
        "FIXTURE_ROOT": quote(FIXTURE_ROOT),
        "GOLDEN": ps_text(context.golden_baseline_path),
        "PUBLIC_KEY": quote(context.public_key),
    }
    script = PRELUDE
    for token, value in values.items():
        script = script.replace(token, value, 1)
    return script


def _step(name: str, operation: str) -> str:
    """One fixture body that always prints its record, pass or fail."""
    body = FIXTURES[name][0 if operation == "setup" else 1]
    return f"""& {{
 try {{
{body}
  $record=[ordered]@{{fixture={quote(name)};operation={quote(operation)};ok=$true;state=$verify}}
 }} catch {{
  $record=[ordered]@{{fixture={quote(name)};operation={quote(operation)};ok=$false;error=[string]$_}}
  $script:fixtureFailed=$true
 }}
 [Console]::Out.WriteLine({quote(VERIFY_MARKER)}+($record | ConvertTo-Json -Compress -Depth 6))
}}
"""


def fixture_script(context: FixtureContext, name: str, operation: str) -> str:
    if name not in FIXTURES or operation not in {"setup", "undo"}:
        raise ValueError(f"unknown machine fixture {name!r} {operation!r}")
    return (
        _prelude(context)
        + _step(name, operation)
        + "if($script:fixtureFailed){exit 1}\n"
    )


def undo_all_script(context: FixtureContext) -> str:
    # Every undo runs even after one fails: each is independent and idempotent.
    return (
        _prelude(context)
        + "".join(_step(name, "undo") for name in UNDO_ORDER)
        + "if($script:fixtureFailed){exit 1}\n"
    )


def fixture_context(control: Any, *, setup: bool) -> FixtureContext:
    """Undo needs only the test user; setup also reads the golden and the key."""
    if not setup:
        return FixtureContext(control.test_user, control.golden_baseline_path or "", "")
    if not control.golden_baseline_path:
        raise HostControlLocalError(
            code=FIXTURE_FAILED,
            phase="machine_fixture",
            detail="No golden baseline is registered for this Test Machine.",
            recovery_hint="Capture and register a native golden before applying machine fixtures.",
        )
    return FixtureContext(
        test_user=control.test_user,
        golden_baseline_path=control.golden_baseline_path,
        public_key=control.project_public_key(),
    )


def _covered(records: list[dict[str, Any]], names: tuple[str, ...], operation: str) -> bool:
    seen = {(r.get("fixture"), r.get("operation")) for r in records if r.get("ok") is True}
    return all((name, operation) in seen for name in names)


def apply_fixture(control: Any, name: str, *, undo: bool) -> list[dict[str, Any]]:
    """Run one fixture's setup or undo as SYSTEM; raise when it is unproved."""
    if name not in FIXTURES:
        raise HostControlLocalError(
            code="machine_fixture_unknown",
            phase="machine_fixture",
            detail=f"No machine fixture is named {name!r}.",
            recovery_hint="Choose one of: " + ", ".join(sorted(FIXTURES)) + ".",
        )
    operation = "undo" if undo else "setup"
    script = fixture_script(fixture_context(control, setup=not undo), name, operation)
    records = control.run_system_script(script, timeout=SYSTEM_SCRIPT_TIMEOUT_SECONDS)
    if not _covered(records, (name,), operation):
        raise MachineFixtureFailed(
            records=records,
            detail=f"The {name} {operation} printed no passing verify record.",
            recovery_hint="Inspect the verify record and rerun the fixture command.",
        )
    return records


def undo_machine_fixtures(control: Any) -> HostActionResult:
    """Run every undo before a reset; a host with no SYSTEM runner has none to undo."""
    try:
        records = control.run_system_script(
            undo_all_script(fixture_context(control, setup=False)),
            timeout=SYSTEM_SCRIPT_TIMEOUT_SECONDS,
        )
    except HostControlLocalError as exc:
        if exc.code == RUNNER_UNAVAILABLE:
            # Without a SYSTEM path no fixture can be applied; the seal still runs.
            return HostActionResult(True, {"skipped": RUNNER_UNAVAILABLE, "reason": exc.detail})
        return HostActionResult(
            False,
            {
                "verify_records": getattr(exc, "records", []),
                "reason": exc.detail,
                "recovery": exc.recovery_hint,
            },
            FIXTURE_FAILED,
        )
    if not _covered(records, UNDO_ORDER, "undo"):
        return HostActionResult(
            False,
            {
                "verify_records": records,
                "reason": "The fixture undo printed no passing record for every fixture.",
                "recovery": "Inspect the verify records; if the undo keeps failing, rebuild the lab in place (native Windows provisioning recovery).",
            },
            FIXTURE_FAILED,
        )
    # A grant just undone leaves the next SSH logon a standard token again.
    control.refresh_host_facts()
    return HostActionResult(True, {"verify_records": records, "order": list(UNDO_ORDER)})


__all__ = [
    "FIXTURES",
    "FIXTURE_ROOT",
    "FixtureContext",
    "SECOND_USER",
    "UNDO_ORDER",
    "apply_fixture",
    "fixture_script",
    "ps_text",
    "undo_all_script",
    "undo_machine_fixtures",
]
