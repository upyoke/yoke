"""Tests for the project VPS reachability doctor check."""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_core.engines.doctor import (
    hc_project_vps_reachable,
)

from runtime.api.engines.test_doctor_project_full import (
    _make_conn,
    _run_hc,
    _seed_capability,
)


class TestProjectVpsReachable:
    def test_warns_when_host_missing(self):
        conn = _make_conn()
        _seed_capability(
            conn, "externalwebapp", "vps-ssh", json.dumps({"user": "ubuntu"})
        )
        rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "WARN"

    def test_passes_when_ssh_succeeds(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "externalwebapp",
            "vps-ssh",
            json.dumps({"host": "example.com"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 0})()
            rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "PASS"

    def test_warns_when_ssh_fails(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "externalwebapp",
            "vps-ssh",
            json.dumps({"host": "example.com"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 1})()
            rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "WARN"

    def test_applicability_is_declared_not_branched_on_a_slug(self):
        """The installation's own project is excluded by declaration."""
        from yoke_core.engines.doctor_applicability import PROJECT_SCOPE_EXTERNAL
        from yoke_core.engines.doctor_applicability_declarations import (
            applicability_for,
        )

        shape = applicability_for("project-vps-reachable")
        assert shape.project_scope == PROJECT_SCOPE_EXTERNAL
        assert shape.required_capabilities == ("vps-ssh",)
