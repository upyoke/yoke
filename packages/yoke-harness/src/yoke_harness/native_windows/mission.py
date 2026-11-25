"""Mission disk, scratch and continuity operations on a native Windows host.

Every step is one PowerShell script over ``WindowsTransport``. The scratch
lives under the test profile at ``AppData\\Local\\YokeQaMission``, which the
profile reset preserves explicitly (``baseline.PRESERVED_DIRECTORIES``) so a
reset inside a walk never deletes a lease's staged secrets; walk-end removes
it, and a reset removes the scratch of every other execution. The disk check reads the system drive's free space.
"""

from __future__ import annotations

import json
from pathlib import PureWindowsPath
from typing import Any, Mapping

from yoke_contracts.qa_mission_scratch import (
    STALE_OWNER_MARKER,
    MissionHostStep,
    MissionScratchProbe,
    mission_scratch_identity,
)
from yoke_contracts.windows_powershell import quote


WINDOWS_MISSION_SCRATCH_DIRECTORY = "AppData/Local/YokeQaMission"
# The transport's error wrapper exits 1, so absence needs its own exit code.
WINDOWS_SCRATCH_ABSENT_EXIT = 3

_UNSAFE_LINK = (
    "foreach($check in @($root,$p)){if((Get-Item -LiteralPath $check -Force)"
    ".Attributes -band [IO.FileAttributes]::ReparsePoint){throw ('mission_scratch_"
    "link_unsafe: remove the link at '+$check+' and re-run the mission')}}"
)


def windows_scratch_create_script(root: str, path: str) -> str:
    """Create the directory and leave only the test user on its ACL."""
    return (
        f"$root={quote(root)}; $p={quote(path)}\n"
        "New-Item -ItemType Directory -Force -Path $p | Out-Null\n"
        + _UNSAFE_LINK
        + "\n"
        "$acl=[Security.AccessControl.DirectorySecurity]::new()\n"
        "$acl.SetAccessRuleProtection($true,$false)\n"
        "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User\n"
        "$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new("
        "$sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))\n"
        "(Get-Item -LiteralPath $p -Force).SetAccessControl($acl)\n"
    )


def windows_scratch_remove_script(path: str) -> str:
    return (
        f"$p={quote(path)}\n"
        "if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Recurse -Force}\n"
    )


def windows_scratch_probe_script(path: str) -> str:
    return (
        f"if(Test-Path -LiteralPath {quote(path)}){{exit 0}}; "
        f"exit {WINDOWS_SCRATCH_ABSENT_EXIT}"
    )


def windows_stale_scratch_script(root: str, kept: tuple[str, ...]) -> str:
    """Remove scratch other executions left behind; the reset keeps the root.

    A mission aborted before walk-end never removes its scratch, so the reset
    deletes every child the running execution does not name. ``rmdir /s``
    deletes links inside without following them.
    """
    keep = ",".join(quote(str(PureWindowsPath(path))) for path in kept)
    return (
        f"$missionRoot={quote(root)}; $missionKeep=@({keep})\n"
        "$missionLeft=@()\n"
        "foreach($entry in @(Get-ChildItem -LiteralPath $missionRoot -Force -ErrorAction SilentlyContinue)){\n"
        " if($missionKeep -contains $entry.FullName){continue}\n"
        " if($entry.Attributes -band [IO.FileAttributes]::Directory){cmd /c rmdir /s /q $entry.FullName 2>&1|Out-Null}\n"
        " else{Remove-Item -LiteralPath $entry.FullName -Force -ErrorAction SilentlyContinue}\n"
        " if($null -ne (Get-Item -LiteralPath $entry.FullName -Force -ErrorAction SilentlyContinue)){$missionLeft+=$entry.FullName}\n"
        "}\n"
        "if($missionLeft.Count){throw ('windows_reset_mission_scratch_left: stale mission scratch remains at '"
        "+($missionLeft -join ', ')+'. Finish or abort its mission, delete it as the test user with cmd /c rmdir /s /q, then rerun yoke test-machine reset')}\n"
    )


def windows_stale_owner_marker_script() -> str:
    marker = str(PureWindowsPath(STALE_OWNER_MARKER))
    return (
        f"$m=Join-Path $env:USERPROFILE {quote(marker)}\n"
        "if(Test-Path -LiteralPath $m){Remove-Item -LiteralPath $m -Force}\n"
        "$h=Join-Path $env:USERPROFILE '.yoke'\n"
        "if((Test-Path -LiteralPath $h -PathType Container) -and "
        "!(Get-ChildItem -LiteralPath $h -Force)){Remove-Item -LiteralPath $h -Force}\n"
    )


def windows_disk_script(minimum_free_bytes: int) -> str:
    minimum = int(minimum_free_bytes)
    return (
        "$drive=[IO.DriveInfo]::new($env:SystemDrive)\n"
        "$free=[int64]$drive.AvailableFreeSpace\n"
        f"$ok=$free -ge {minimum}\n"
        "ConvertTo-Json -Compress -InputObject @{ok=$ok;free_bytes=$free;"
        f"minimum_free_bytes={minimum};drive=$env:SystemDrive;"
        "error_code=$(if($ok){$null}else{'test_machine_disk_space_low'})}\n"
    )


def windows_continuity_script(fingerprint: Mapping[str, str]) -> str:
    """Hash each recorded file; ``~/`` resolves under the test profile."""
    return (
        f"$expected=ConvertFrom-Json {quote(json.dumps(dict(fingerprint)))}\n"
        "$failures=@()\n"
        "foreach($entry in $expected.PSObject.Properties){\n"
        " $name=$entry.Name\n"
        " $path=if($name.StartsWith('~/')){Join-Path $env:USERPROFILE $name.Substring(2)}else{$name}\n"
        " try{\n"
        "  $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop\n"
        "  if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){\n"
        "   $failures+=@{path=$name;reason='missing_or_not_regular'}; continue\n"
        "  }\n"
        "  $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()\n"
        "  if($hash -ne $entry.Value){$failures+=@{path=$name;reason='changed'}}\n"
        " } catch [Management.Automation.ItemNotFoundException] {\n"
        "  $failures+=@{path=$name;reason='missing_or_not_regular'}\n"
        " } catch {$failures+=@{path=$name;reason='unreadable'}}\n"
        "}\n"
        "ConvertTo-Json -Compress -Depth 4 -InputObject @{ok=($failures.Count -eq 0);failures=@($failures)}\n"
    )


def _step(control: Any, label: str, script: str, timeout: int) -> MissionHostStep:
    completed = control._run(script, timeout=timeout)
    return MissionHostStep(
        command=label,
        returncode=int(completed.returncode),
        stderr=(getattr(completed, "stderr", "") or "").strip(),
    )


class WindowsMissionOperations:
    """``MissionHostOperations`` for a native Windows host."""

    @property
    def mission_scratch_root(self) -> str:
        return str(PureWindowsPath(self.home) / WINDOWS_MISSION_SCRATCH_DIRECTORY)

    def mission_scratch_path(self, execution_id: str) -> str:
        identity = mission_scratch_identity(execution_id)
        return str(PureWindowsPath(self.mission_scratch_root) / identity)

    def require_mission_disk_space(self) -> dict[str, Any]:
        from yoke_harness.test_machine_temp_script import MINIMUM_MISSION_FREE_BYTES
        from yoke_harness.test_machine_temp_state import (
            refuse_unadmitted_disk,
            temp_receipt,
        )

        result = self._run(windows_disk_script(MINIMUM_MISSION_FREE_BYTES), timeout=60)
        return refuse_unadmitted_disk(temp_receipt(result))

    def create_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep:
        script = windows_scratch_create_script(self.mission_scratch_root, path)
        return _step(self, f"create owner-only directory {path}", script, timeout)

    def remove_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep:
        script = windows_scratch_remove_script(path)
        return _step(self, f"Remove-Item -Recurse -Force {path}", script, timeout)

    def probe_mission_scratch(
        self, path: str, *, timeout: int = 60
    ) -> MissionScratchProbe:
        step = _step(
            self, f"Test-Path {path}", windows_scratch_probe_script(path), timeout
        )
        state = {0: "present", WINDOWS_SCRATCH_ABSENT_EXIT: "absent"}.get(
            step.returncode, "unknown"
        )
        return MissionScratchProbe(state=state, step=step)

    def remove_stale_owner_marker(self, *, timeout: int = 60) -> MissionHostStep:
        return _step(
            self,
            f"Remove-Item ~/{STALE_OWNER_MARKER}",
            windows_stale_owner_marker_script(),
            timeout,
        )

    def check_continuity_files(self, fingerprint: Mapping[str, str]) -> dict[str, Any]:
        completed = self._run(windows_continuity_script(fingerprint), timeout=30)
        if int(completed.returncode) != 0:
            return {"ok": False, "failures": [{"reason": "check_failed"}]}
        return json.loads(completed.stdout)


__all__ = [
    "WINDOWS_MISSION_SCRATCH_DIRECTORY",
    "WINDOWS_SCRATCH_ABSENT_EXIT",
    "WindowsMissionOperations",
    "windows_continuity_script",
    "windows_disk_script",
    "windows_scratch_create_script",
    "windows_scratch_probe_script",
    "windows_scratch_remove_script",
    "windows_stale_owner_marker_script",
]
