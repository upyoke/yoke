"""Collector probes request the machine format their JSON parser consumes."""

import io
from types import SimpleNamespace

import pytest

from ops.qa import collector_device_classification, collector_refusal_receipt
from yoke_cli.commands.adapters.db import _write_json


@pytest.mark.parametrize(
    "probe", [collector_refusal_receipt, collector_device_classification]
)
def test_probe_parses_explicit_json_db_output(monkeypatch, probe):
    rows = [["Chrome", "macOS", "desktop"]]

    def run(argv, **kwargs):
        assert argv[:3] == ["yoke", "db", "read"]
        assert argv[-2:] == ["--format", "json"]
        out = io.StringIO()
        _write_json(
            SimpleNamespace(
                result={"rows": rows, "columns": ["browser", "os", "device_type"]},
                warnings=[],
            ),
            out,
            io.StringIO(),
        )
        return SimpleNamespace(returncode=0, stdout=out.getvalue())

    monkeypatch.setattr(probe.subprocess, "run", run)
    if probe is collector_refusal_receipt:
        assert probe.read("SELECT browser, os, device_type FROM events") == rows
    else:
        assert probe.stored_device("example-event") == tuple(rows[0])
