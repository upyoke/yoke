"""Native runtime health and install report delivery."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_cli.project_install import instruction_discovery as instructions
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.local_source_preview import preview_report
from yoke_core.domain.project_install_test_helpers import make_bundle


def _runtimes(monkeypatch, versions):
    original_which = instructions.shutil.which
    original_run = instructions.terminal_detached_process.run
    monkeypatch.setattr(
        instructions.shutil,
        "which",
        lambda name: (
            f"/native/{name}"
            if name in versions
            else (
                None
                if name in {"claude", "codex", "cursor-agent"}
                else original_which(name)
            )
        ),
    )

    def probe(argv, **kwargs):
        name = argv[0].rsplit("/", 1)[-1]
        if name not in versions:
            return original_run(argv, **kwargs)
        value = versions[name]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(stdout=value[0], returncode=value[1])

    monkeypatch.setattr(instructions.terminal_detached_process, "run", probe)


def test_unused_old_codex_health_with_supported_cursor(tmp_path, monkeypatch):
    _runtimes(
        monkeypatch,
        {"codex": ("codex-cli 0.149.1", 0), "cursor-agent": ("2026.10.14-build", 0)},
    )
    health = instructions.preflight(tmp_path)
    assert len(health) == 3
    codex = next(row for row in health if row["cli"] == "codex")
    assert codex["detected_version"] == "0.149.1"
    assert codex["floor"] == "0.161.0"
    assert codex["status"] == "below_floor"
    assert "Codex sessions won't load AGENTS.md/skills" in codex["effect"]
    assert "Install or upgrade" in codex["next_step"]
    assert "new session" in codex["next_step"]
    assert next(row for row in health if row["cli"] == "cursor-agent")["status"] == "ok"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "versions",
    [
        {"codex": ("0.149.1", 0)},
        {"codex": ("0.149.1", 0), "cursor-agent": ("2026.09.30", 0)},
        {"codex": ("0.161.0", 1)},
    ],
)
def test_no_passing_runtime_reports_health_without_writing(
    tmp_path, monkeypatch, versions
):
    _runtimes(monkeypatch, versions)
    health = instructions.preflight(tmp_path)
    assert all(row["status"] != "ok" for row in health)
    assert all("AGENTS.md/skills" in row["effect"] for row in health)
    assert all("Install or upgrade" in row["next_step"] for row in health)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "broken",
    [
        ("not a version", 0),
        ("0.161.0", 1),
        OSError("unavailable"),
        subprocess.TimeoutExpired("codex", 10),
    ],
)
def test_broken_probe_health_with_supported_cursor(tmp_path, monkeypatch, broken):
    _runtimes(monkeypatch, {"codex": broken, "cursor-agent": ("2026.10.14", 0)})
    codex = next(
        row for row in instructions.preflight(tmp_path) if row["cli"] == "codex"
    )
    assert codex["status"] == "probe_failed"
    assert codex["detected_version"] is None
    assert codex["floor"] == "0.161.0"
    assert "cannot be verified" in codex["effect"]


def test_supported_floor_reports_ok(tmp_path, monkeypatch):
    _runtimes(monkeypatch, {"codex": ("codex-cli 0.161.0", 0)})
    codex = next(
        row for row in instructions.preflight(tmp_path) if row["cli"] == "codex"
    )
    assert codex["status"] == "ok"
    assert codex["detected_version"] == "0.161.0"


def test_absent_clis_allow_guidance_for_a_later_harness(tmp_path, monkeypatch):
    _runtimes(monkeypatch, {})
    health = instructions.preflight(tmp_path)
    assert len(health) == 3
    assert all(row["status"] == "absent" for row in health)
    assert all(row["detected_version"] is None for row in health)


@pytest.mark.parametrize("preview", [False, True])
def test_runtime_health_reaches_install_and_preview_report(
    tmp_path, monkeypatch, preview, capsys
):
    _runtimes(monkeypatch, {"codex": ("0.149.1", 0), "cursor-agent": ("2026.10.14", 0)})
    bundle = make_bundle()
    bundle["hooks"]["cursor_hooks"] = {}
    if preview:
        report = preview_report(
            tmp_path,
            bundle,
            prior_manifest={},
            manifest_source="test",
            source_label="source:test",
            preserved_files={},
        )
        assert not (tmp_path / ".yoke/install-manifest.json").exists()
    else:
        report = apply_bundle(tmp_path, bundle, source="test")
        assert (tmp_path / ".yoke/install-manifest.json").is_file()
    assert report["warnings"] == []
    codex = next(row for row in report["harness_health"] if row["cli"] == "codex")
    assert codex["status"] == "below_floor"
    from yoke_cli.commands.adapters.install import _run

    assert _run(lambda: report) == 0
    output = capsys.readouterr().out
    assert "harness health:" in output
    assert "below_floor" in output
    assert "0.149.1" in output
    assert "Install or upgrade codex" in output
