"""Retire only unregistered native goldens after a verified capture."""

import json
from pathlib import PureWindowsPath

from yoke_harness.native_windows.baseline import golden_path
from yoke_harness.native_windows.transport import quote


def retain(control, destination, kept_paths):
    from yoke_harness.golden_snapshot_retention import (
        removable_snapshot_names,
        removal_order,
        SnapshotRetentionError,
    )

    destination = golden_path(control, destination)
    parent = PureWindowsPath(destination).parent
    kept = {
        PureWindowsPath(path).name
        for path in kept_paths
        if PureWindowsPath(path).parent == parent
    }
    result = control._run(f"""
$parent=Get-Item -LiteralPath {quote(str(parent))}
if($parent.Attributes -band [IO.FileAttributes]::ReparsePoint){{throw 'windows_golden_parent_link: remove the golden parent link before retention'}}
$when=(Get-Item -LiteralPath {quote(destination)}).LastWriteTimeUtc
ConvertTo-Json -Compress -InputObject @((Get-ChildItem -LiteralPath $parent.FullName | Where-Object {{$_.LastWriteTimeUtc -le $when}}).Name)
""")
    recovery = "Preserve registered goldens, repair the native golden parent, and retry capture."
    if result.returncode:
        raise SnapshotRetentionError(
            "Native golden listing failed: " + result.stderr[-400:], recovery
        )
    names = json.loads(result.stdout)
    removable = removal_order(
        removable_snapshot_names(
            names,
            registered_names=sorted(kept),
            user=control._user,
            parent_name=parent.name,
        )
    )
    if not removable:
        return []
    paths = ",".join(quote(str(parent / name)) for name in removable)
    removed = control._run(
        f"""
foreach($path in @({paths})){{
 $entries=@(Get-Item -LiteralPath $path)+@(Get-ChildItem -LiteralPath $path -Recurse -Force)
 if($entries | Where-Object {{$_.Attributes -band [IO.FileAttributes]::ReparsePoint}}){{throw 'windows_golden_link_refused: preserve linked entries and repair the golden'}}
 $entries | ForEach-Object {{$_.Attributes=$_.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly)}}
 Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
}}
""",
        timeout=300,
    )
    if removed.returncode:
        raise SnapshotRetentionError(
            "Native golden removal failed: " + removed.stderr[-400:], recovery
        )
    return removable
