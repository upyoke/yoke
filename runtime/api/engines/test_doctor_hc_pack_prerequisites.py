from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.packs import prerequisites
from yoke_core.engines import doctor_hc_pack_prerequisites
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _write_receipt(checkout: Path) -> None:
    path = checkout / ".yoke" / "packs.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": 3,
                "project_id": 7,
                "project_slug": "sample",
                "packs": {
                    "container-runtime": {
                        "version": "1.0.0",
                        "content_digest": "a" * 64,
                        "render_values": {},
                        "prerequisites": [
                            {
                                "tool": "docker",
                                "minimum_version": "20.10.0",
                                "probe": {
                                    "executable": "docker",
                                    "version_args": ["--version"],
                                },
                                "install": {
                                    "darwin": "brew install --cask docker",
                                    "linux": "install docker on linux",
                                    "windows": "winget install Docker.DockerDesktop",
                                },
                            }
                        ],
                        "files": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_doctor_names_missing_pack_tool_and_recovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _write_receipt(tmp_path)
    monkeypatch.setattr(
        doctor_hc_pack_prerequisites,
        "resolve_context",
        lambda conn, args: SimpleNamespace(source_checkout=tmp_path),
    )
    monkeypatch.setattr(prerequisites, "_WHICH", lambda executable: None)
    monkeypatch.setattr(prerequisites, "_SYSTEM", lambda: "Darwin")
    collector = RecordCollector()

    doctor_hc_pack_prerequisites.hc_pack_prerequisites(
        object(), DoctorArgs(project="sample"), collector
    )

    [result] = collector.results
    assert result.result == "FAIL"
    assert "pack-prerequisite-missing" in result.detail
    assert "container-runtime/docker" in result.detail
    assert "brew install --cask docker" in result.detail


def test_doctor_passes_when_no_pack_receipt_exists(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        doctor_hc_pack_prerequisites,
        "resolve_context",
        lambda conn, args: SimpleNamespace(source_checkout=tmp_path),
    )
    collector = RecordCollector()

    doctor_hc_pack_prerequisites.hc_pack_prerequisites(
        object(), DoctorArgs(project="sample"), collector
    )

    [result] = collector.results
    assert result.result == "PASS"
    assert "no installed prerequisites" in result.detail
