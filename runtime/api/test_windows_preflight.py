"""Machine scenario verdicts are portable: no Windows host is needed."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform

import pytest

from yoke_contracts.windows_preflight import verdicts
from yoke_contracts.windows_preflight_facts import collect_facts, name_facts


pytestmark = pytest.mark.windows


def facts(**overrides):
    return {
        "system": "Windows",
        "build": 26100,
        "edition": "Windows 11 Enterprise",
        "arch": "AMD64",
        "elevated": False,
        "git": "git.exe",
        "ssh": "ssh.exe",
        "storage": [
            {"path": "C:/Users/José Smith/.yoke", "kind": "local", "filesystem": "NTFS"}
        ],
        "repo": "C:/src/repo",
        "long_paths_enabled": False,
        "longest_path": 100,
        "desktop": True,
        "browser": True,
        **overrides,
    }


def row(code, **overrides):
    return next(
        r for r in verdicts(facts(**overrides)) if r["code"] == "windows_" + code
    )


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_other_os_setup_unchanged(system):
    assert verdicts(facts(system=system, elevated=True, blocked_hosts=["host"])) == []


@pytest.mark.parametrize(
    "edition,build,arch",
    [
        ("Windows 11 Enterprise", 26100, "AMD64"),
        ("Windows 11 Pro", 26100, "AMD64"),
        ("Windows 11 Home", 26100, "AMD64"),
        ("Windows 10 Pro", 19045, "AMD64"),
        ("Windows Server 2019", 17763, "AMD64"),
        ("Windows Server 2025", 26100, "AMD64"),
        ("Windows 11 Enterprise", 26100, "ARM64"),
    ],
)
def test_target_versions_remain_untested_not_support_claims(edition, build, arch):
    result = row("coverage_untested", edition=edition, build=build, arch=arch)
    assert result["severity"] == "warning"
    assert str(build) in result["message"] and edition in result["message"]
    assert "untested" in result["message"]


@pytest.mark.parametrize(
    "changes",
    [
        {"build": 9600},
        {"arch": "x86"},
        {"build": 14393, "edition": "Windows Server 2016"},
    ],
)
def test_unsupported_versions_refuse_with_recovery(changes):
    result = row("version", **changes)
    assert result["severity"] == "error" and "Use Windows" in result["hint"]


@pytest.mark.parametrize("elevated", [False, True])
def test_per_user_elevation_verdict(elevated):
    result = row("elevation", elevated=elevated)
    assert result["severity"] == ("warning" if elevated else "info")
    assert "per-user" in result["hint"]


@pytest.mark.parametrize(
    "kind,fs",
    [
        ("onedrive", "NTFS"),
        ("network", "NTFS"),
        ("roaming", "NTFS"),
        ("local", "exFAT"),
        ("local", "FAT32"),
    ],
)
def test_secrets_and_database_refuse_unsafe_storage(kind, fs):
    result = row(
        "private_storage", storage=[{"path": "D:/home", "kind": kind, "filesystem": fs}]
    )
    assert result["severity"] == "error" and "D:/home" in result["message"]
    assert "local NTFS" in result["hint"]


def test_unicode_and_spaces_are_valid_local_storage():
    assert row("private_storage")["severity"] == "info"


@pytest.mark.parametrize(
    "changes", [{"edition": "Windows 11 Education"}, {"build": "bad"}]
)
def test_unknown_edition_and_malformed_build_refuse(changes):
    assert row("version", **changes)["severity"] == "error"


def test_unknown_drive_is_not_a_pass():
    assert row("storage_unknown", storage=[{"path": "Z:/home"}])["severity"] == "error"


@pytest.mark.parametrize(
    "enabled,length,refuses",
    [(False, 259, False), (False, 260, True), (True, 300, False)],
)
def test_long_path_limit(enabled, length, refuses):
    result = row("long_paths", long_paths_enabled=enabled, longest_path=length)
    assert (result["severity"] == "error") == refuses


@pytest.mark.parametrize(
    "repo", [r"\\wsl$\Ubuntu\home\repo", r"\\wsl.localhost\Ubuntu\repo"]
)
def test_wsl_repo_has_a_named_owner(repo):
    result = row("wsl_repository", repo=repo)
    assert result["severity"] == "error" and "inside that WSL" in result["hint"]


def test_reserved_and_colliding_files_and_branches():
    invalid, collisions = name_facts(
        [
            "con.txt",
            "dir/NUL",
            "branch/AUX",
            "trail.",
            "Foo/a",
            "foo/b",
            "branch/Fix",
            "branch/fix",
        ]
    )
    assert invalid == ["con.txt", "dir/NUL", "branch/AUX", "trail."]
    assert ["Foo", "foo"] in collisions and ["branch/Fix", "branch/fix"] in collisions
    results = verdicts(facts(invalid_names=invalid, colliding_names=collisions))
    errors = [r for r in results if r["severity"] == "error"]
    assert len(errors) == 6 and all(r["hint"].startswith("Rename") for r in errors)


@pytest.mark.parametrize("tool", ["git", "ssh"])
def test_missing_tools_name_install_step(tool):
    result = row(tool, **{tool: None})
    assert result["severity"] == "warning" and "Install step" in result["hint"]


def test_wsl_install_keeps_identity_separate():
    assert (
        "separate homes and machine identities"
        in row("wsl_install", wsl_yoke=True)["message"]
    )


@pytest.mark.parametrize(
    "desktop,browser", [(False, True), (True, False), (False, False)]
)
def test_headless_uses_existing_connect_code_flow(desktop, browser):
    assert "yoke connect" in row("code_flow", desktop=desktop, browser=browser)["hint"]


def test_store_and_download_host_blocks_name_recovery():
    assert "native direct installer" in row("store_blocked", store_blocked=True)["hint"]
    result = row("download_host", blocked_hosts=["downloads.cursor.com"])
    assert (
        "downloads.cursor.com" in result["message"]
        and "proxy/firewall" in result["hint"]
    )


@pytest.mark.parametrize("policy", ["AppLocker", "WDAC", "Smart App Control"])
def test_policy_blocks_show_file_and_evidence(policy):
    result = row(
        "application_control",
        policy_blocks=[
            {
                "policy": policy,
                "file": "C:/yoke/python.exe",
                "evidence": "policy enforced event 3077",
            }
        ],
    )
    assert result["severity"] == "error" and "python.exe" in result["message"]
    assert "3077" in result["message"] and "no per-app exception" in result["hint"]


def test_inaccessible_probe_is_not_success():
    assert (
        row("probe_incomplete", probe_errors=["event log access denied"])["severity"]
        == "warning"
    )


def test_real_runner_facts_are_recorded():
    collected = collect_facts()
    print("NATIVE_PREFLIGHT_RUNNER_FACTS=" + json.dumps(collected, ensure_ascii=True))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
            "a", encoding="utf-8"
        ) as summary:
            summary.write(
                "\n### Native preflight runner facts\n```json\n"
                + json.dumps(collected, ensure_ascii=True, indent=2)
                + "\n```\n"
            )
    assert collected["system"] == platform.system()
    if platform.system() == "Windows":
        assert collected["build"] >= 17763
        assert collected["edition"] and collected["arch"] and collected["storage"]
        assert isinstance(collected["policy_blocks"], list)
