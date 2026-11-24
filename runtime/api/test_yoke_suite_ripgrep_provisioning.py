"""Windows suite shards use a checked and versioned ripgrep release."""

from __future__ import annotations

from pathlib import Path
import re

from yoke_core.domain.yaml_helper import load_document

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "yoke-suite.yml"


def test_windows_ripgrep_download_is_pinned_and_verified_before_extraction() -> None:
    suite = load_document(_WORKFLOW)["jobs"]["suite"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", suite["env"]["RIPGREP_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", suite["env"]["RIPGREP_SHA256"])

    steps = {step.get("name"): step for step in suite["steps"]}
    script = steps["Provision Windows shell and symlinks"]["run"]
    assert "ripgrep-$env:RIPGREP_VERSION-x86_64-pc-windows-msvc" in script
    release_url = (
        "https://github.com/BurntSushi/ripgrep/releases/download/"
        "$env:RIPGREP_VERSION/$asset.zip"
    )
    assert release_url in script
    download = script.index("Invoke-WebRequest -Uri $url -OutFile $archive")
    hash_check = script.index("Get-FileHash -LiteralPath $archive -Algorithm SHA256")
    mismatch = script.index("if ($digest -ne $env:RIPGREP_SHA256)")
    refusal = script.index('throw "ripgrep SHA256 mismatch')
    extraction = script.index("Expand-Archive -LiteralPath $archive")
    assert download < hash_check < mismatch < refusal < extraction


def test_windows_ripgrep_cache_saves_verified_files_only_on_a_miss() -> None:
    suite = load_document(_WORKFLOW)["jobs"]["suite"]
    steps = {step.get("name"): step for step in suite["steps"]}
    restore = steps["Restore Windows ripgrep cache"]
    provision = steps["Provision Windows shell and symlinks"]
    save = steps["Save Windows ripgrep cache"]

    names = list(steps)
    assert names.index(restore["name"]) < names.index(provision["name"]) < names.index(save["name"])
    assert restore["uses"].startswith("actions/cache/restore@")
    assert save["uses"].startswith("actions/cache/save@")
    assert "${{ env.RIPGREP_VERSION }}" in restore["with"]["key"]
    assert "${{ env.RIPGREP_SHA256 }}" in restore["with"]["key"]
    assert provision["env"]["RIPGREP_CACHE_HIT"] == "${{ steps.ripgrep-cache.outputs.cache-hit }}"
    assert save["with"]["key"] == "${{ steps.ripgrep-cache.outputs.cache-primary-key }}"
    assert save["with"]["path"] == restore["with"]["path"]
    assert save["if"] == "matrix.os == 'windows' && steps.ripgrep-cache.outputs.cache-hit != 'true'"
