from __future__ import annotations

import subprocess

from yoke_cli.packs import prerequisites


def _declaration(tool: str = "pulumi", minimum: str = "3.0.0") -> dict:
    return {
        "tool": tool,
        "minimum_version": minimum,
        "probe": {"executable": tool, "version_args": ["version"]},
        "install": {
            "darwin": f"brew install {tool}",
            "linux": f"install {tool} on linux",
            "windows": f"winget install {tool}",
        },
    }


def test_probe_reports_named_missing_tool_with_host_recipe(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")

    [row] = prerequisites.probe_prerequisites([_declaration()])

    assert row["status"] == "missing"
    assert row["code"] == "pack-prerequisite-missing"
    assert row["tool"] == "pulumi"
    assert row["install_recipe"] == "brew install pulumi"
    assert "pulumi 3.0.0 or newer" in row["detail"]


def test_probe_accepts_version_output_with_a_prefix(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: "/bin/tool")
    monkeypatch.setattr(
        prerequisites,
        "_RUN",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "v3.125.0\n", None
        ),
    )

    [row] = prerequisites.probe_prerequisites([_declaration()])

    assert row["status"] == "ready"
    assert row["code"] == "pack-prerequisite-ready"
    assert row["observed_version"] == "3.125.0"


def test_probe_rejects_a_version_below_the_floor(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: "/bin/tool")
    monkeypatch.setattr(
        prerequisites,
        "_RUN",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "pulumi v2.99.1\n", None
        ),
    )

    [row] = prerequisites.probe_prerequisites([_declaration()])

    assert row["status"] == "outdated"
    assert row["code"] == "pack-prerequisite-outdated"
    assert row["observed_version"] == "2.99.1"


def test_duplicate_pack_contracts_share_one_machine_probe(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: "/bin/tool")

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(args[0], 0, "3.2.1", None)

    monkeypatch.setattr(prerequisites, "_RUN", fake_run)

    rows = prerequisites.probe_pack_prerequisites(
        [("foundation", [_declaration()]), ("hosting", [_declaration()])]
    )

    assert [row["pack"] for row in rows] == ["foundation", "hosting"]
    assert len(calls) == 1
