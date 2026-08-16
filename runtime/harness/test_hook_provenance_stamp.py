"""Execution provenance line names client and optional server fingerprints."""

from __future__ import annotations

from yoke_core.domain.execution_provenance import (
    PROVENANCE_KEYS,
    collect_execution_provenance,
    format_provenance_line,
)


def test_collect_execution_provenance_has_required_keys() -> None:
    blob = collect_execution_provenance()
    assert tuple(blob) == PROVENANCE_KEYS
    assert blob["source_sha"]
    assert blob["install_kind"]
    assert blob["install_path"]


def test_format_provenance_line_client_and_server_and_fallback() -> None:
    client = {
        "source_sha": "aaa",
        "install_kind": "source_checkout",
        "install_path": "/client",
    }
    server = {
        "source_sha": "bbb",
        "install_kind": "installed_wheel",
        "install_path": "/server",
    }
    line = format_provenance_line(client, server, fallback_local=True)
    assert line.startswith("yoke-provenance ")
    assert "client sha=aaa" in line
    assert "server sha=bbb" in line
    assert "fallback=local" in line
