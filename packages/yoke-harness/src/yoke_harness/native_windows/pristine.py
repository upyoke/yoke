"""Keep native Windows goldens free of Yoke command staging and uv's registry.

Long commands run from `%USERPROFILE%\\.yoke-stage-<uuid>` (standard_staging.py),
and `uv python install` registers its Python under HKCU\\Software\\Python\\Astral,
which the profile mirror never restores. Neither may enter or survive a golden.
"""

import json

from yoke_contracts.test_machine_types import HostActionResult
from yoke_contracts.windows_powershell import quote


STAGE_FILTER = ".yoke-stage-*"
UV_PYTHON_REGISTRY = r"HKCU:\Software\Python\Astral"

# Inserted into the profile mirror after $source and $target are set: robocopy
# rejects a wildcard in an absolute /XD path, so name each root stage folder.
STAGE_COPY_EXCLUSION = f"""foreach($root in @($source,$target)){{
 if(Test-Path -LiteralPath $root -PathType Container){{
  $exclude+=@(Get-ChildItem -LiteralPath $root -Directory -Force -Filter '{STAGE_FILTER}' | Select-Object -ExpandProperty FullName)
 }}
}}
"""

# Reset keeps only the stage folder running this script, then drops uv's
# registry entry. A linked stage folder loses only its link, never its target.
RESIDUE_CLEANUP = f"""$ownStage=if($PSCommandPath){{Split-Path -Parent $PSCommandPath}}else{{''}}
foreach($stage in @(Get-ChildItem -LiteralPath $profileRoot -Directory -Force -Filter '{STAGE_FILTER}')){{
 if($stage.FullName -eq $ownStage){{continue}}
 if($stage.Attributes -band [IO.FileAttributes]::ReparsePoint){{$stage.Delete()}}else{{Remove-Item -LiteralPath $stage.FullName -Recurse -Force}}
}}
if(Test-Path -LiteralPath '{UV_PYTHON_REGISTRY}'){{Remove-Item -LiteralPath '{UV_PYTHON_REGISTRY}' -Recurse -Force}}
"""


def residue_script(home):
    return (
        f"$stages=@(Get-ChildItem -LiteralPath {quote(home)} -Directory -Force -Filter '{STAGE_FILTER}' | "
        "Select-Object -ExpandProperty Name); "
        f"ConvertTo-Json -Compress @{{stage_folders=$stages;uv_python_registry=[bool](Test-Path -LiteralPath '{UV_PYTHON_REGISTRY}')}}"
    )


RECOVERY = {
    "capture": (
        "Run yoke test-machine reset to remove the named Yoke stage folders and the uv "
        "Python registry key, then capture into a new golden path."
    ),
    "reset": (
        "Reset could not remove the named residue: close the process holding it, remove it "
        "from the test profile, then rerun yoke test-machine reset."
    ),
}


def residue_refusal(control, operation):
    """Return a refusal when the profile holds residue, or None when it is pristine.

    The probe runs inline, so no stage folder of its own exists while it looks.
    """
    result = control._run(residue_script(control.home), timeout=30)
    try:
        found = json.loads(result.stdout) if result.returncode == 0 else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        return HostActionResult(
            False,
            {
                "operation": operation,
                "recovery": (result.stderr or "").strip()
                or "The profile residue probe returned no answer; repair SSH or PowerShell and retry.",
            },
            "windows_profile_residue_unproved",
        )
    stages = found.get("stage_folders") or []
    residue = {
        "stage_folders": sorted([stages] if isinstance(stages, str) else stages),
        "uv_python_registry": found.get("uv_python_registry") is True,
    }
    if not residue["stage_folders"] and not residue["uv_python_registry"]:
        return None
    return HostActionResult(
        False,
        {"operation": operation, "profile_residue": residue, "recovery": RECOVERY[operation]},
        "windows_profile_not_pristine",
    )
