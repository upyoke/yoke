"""Native runtime admission and install-health warning delivery."""

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


def test_unused_old_codex_warns_when_cursor_is_supported(tmp_path, monkeypatch):
    _runtimes(
        monkeypatch,
        {"codex": ("codex-cli 0.149.1", 0), "cursor-agent": ("2026.10.14-build", 0)},
    )
    warnings = instructions.preflight(tmp_path)
    assert len(warnings) == 1
    warning = warnings[0]
    for expected in (
        "codex",
        "0.149.1",
        "0.161.0",
        "Codex sessions",
        "won't load AGENTS.md/skills",
        "Upgrade",
        "new session",
    ):
        assert expected in warning
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "versions",
    [
        {"codex": ("0.149.1", 0)},
        {"codex": ("0.149.1", 0), "cursor-agent": ("2026.09.30", 0)},
        {"codex": ("0.161.0", 1)},
    ],
)
def test_no_passing_runtime_warns_without_writing(tmp_path, monkeypatch, versions):
    _runtimes(monkeypatch, versions)
    warnings = instructions.preflight(tmp_path)
    assert "no supported agent CLI detected" in warnings[-1]
    assert "AGENTS.md/skills" in warnings[-1]
    assert "Install or upgrade" in warnings[-1]
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
def test_broken_probe_warns_with_supported_cursor(tmp_path, monkeypatch, broken):
    _runtimes(monkeypatch, {"codex": broken, "cursor-agent": ("2026.10.14", 0)})
    warnings = instructions.preflight(tmp_path)
    assert len(warnings) == 1
    assert "unknown (version probe failed)" in warnings[0]
    assert "required >=0.161.0" in warnings[0]


def test_supported_floor_needs_no_warning(tmp_path, monkeypatch):
    _runtimes(monkeypatch, {"codex": ("codex-cli 0.161.0", 0)})
    assert instructions.preflight(tmp_path) == []


def test_absent_clis_allow_guidance_for_a_later_harness(tmp_path, monkeypatch):
    _runtimes(monkeypatch, {})
    warnings = instructions.preflight(tmp_path)
    assert len(warnings) == 1
    assert "instruction_runtime_unavailable" in warnings[0]


@pytest.mark.parametrize("preview", [False, True])
def test_runtime_warning_reaches_install_and_preview_report(
    tmp_path, monkeypatch, preview
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
    assert any("codex version 0.149.1" in warning for warning in report["warnings"])
