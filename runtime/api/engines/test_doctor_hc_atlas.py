"""Tests for HC-atlas-integrity.

Each contradiction class has a PASS and a FAIL case driven by monkey-
patched audit fixtures. The HC self-skips to WARN when the audit
infrastructure raises, which is exercised separately.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_project_checks import check_atlas as mod
from yoke_project_checks.check_atlas import hc_atlas_integrity
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _clean_report() -> dict:
    return {
        "function_registry": {
            "count": 2,
            "rows": [
                {"function_id": "items.get.run"},
                {"function_id": "claims.work.acquire"},
            ],
        },
        "yoke_cli": {
            "count": 2,
            "rows": [
                {"cli_form": "yoke items get", "function_id": "items.get.run",
                 "cli_tokens": ["items", "get"]},
                {"cli_form": "yoke claims work acquire",
                 "function_id": "claims.work.acquire",
                 "cli_tokens": ["claims", "work", "acquire"]},
            ],
        },
        "operation_tracker": {
            "rows": [
                {"shell_form": "yoke items get", "status": "wrapped"},
                {"shell_form": "yoke claims work acquire", "status": "wrapped"},
            ],
        },
        "help_pages": {
            "per_subcommand": {
                "items get": {"exit_code": 0, "body": "ok", "stderr": ""},
                "claims work acquire": {"exit_code": 0, "body": "ok", "stderr": ""},
            },
        },
        "taught_commands": {"count": 0, "drift_count": 0, "surfaces": []},
        "summary": {},
    }


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _record(report: dict, conn, monkeypatch, *, atlas_stale: bool = False,
            fn_inv_path_exists: bool = False, fn_inv_text: str = "") -> RecordCollector:
    monkeypatch.setattr(mod, "_build_audit_report", lambda: report)

    # Stub the renderer + staleness check.
    import yoke_core.tools.atlas_render_docs as ard_mod
    monkeypatch.setattr(ard_mod, "render", lambda r: "rendered body")
    monkeypatch.setattr(ard_mod, "is_stale", lambda root, *, body: atlas_stale)

    # Stub function-inventory file state by patching Path semantics.
    class _FakePath:
        def __init__(self, exists: bool, text: str) -> None:
            self._exists = exists
            self._text = text

        def exists(self) -> bool:
            return self._exists

        def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
            return self._text

    real_repo_root = mod._repo_root

    def stub_repo_root():
        class _Root:
            def __truediv__(self, _):
                # docs / function-inventory.md
                class _Inner:
                    def __truediv__(self, _):
                        return _FakePath(fn_inv_path_exists, fn_inv_text)
                return _Inner()
        return _Root() if (fn_inv_path_exists or fn_inv_text) else real_repo_root()

    monkeypatch.setattr(mod, "_repo_root", stub_repo_root)

    rec = RecordCollector()
    hc_atlas_integrity(conn, DoctorArgs(), rec)
    return rec


class TestPass:
    def test_live_repo_atlas_is_current(
        self, conn, monkeypatch, tmp_path,
    ) -> None:
        import yoke_core.tools.atlas_integrity_audit as audit_mod
        import yoke_core.tools.atlas_render_docs as ard_mod

        monkeypatch.setattr(
            audit_mod,
            "collect_field_notes",
            lambda: {
                "count": 0,
                "rows": [],
                "read_surface_status": "agent_facing",
            },
        )
        report = mod._build_audit_report()
        rendered = tmp_path / "docs" / "atlas.md"
        rendered.parent.mkdir()
        rendered.write_text(ard_mod.render(report), encoding="utf-8")
        monkeypatch.setattr(mod, "_build_audit_report", lambda: report)
        monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
        rec = RecordCollector()

        hc_atlas_integrity(conn, DoctorArgs(project="yoke"), rec)

        assert rec.results[0].result == "PASS", rec.results[0].detail

    def test_clean_report_passes(self, conn, monkeypatch, tmp_path) -> None:
        # Point repo_root at tmp_path so docs/atlas.md is "missing"
        # — but we override is_stale to False to focus on the other checks.
        monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
        import yoke_core.tools.atlas_render_docs as ard_mod
        monkeypatch.setattr(ard_mod, "render", lambda r: "x")
        monkeypatch.setattr(ard_mod, "is_stale", lambda root, *, body: False)
        monkeypatch.setattr(mod, "_build_audit_report", lambda: _clean_report())
        rec = RecordCollector()
        hc_atlas_integrity(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS", rec.results[0].detail

    def test_clean_report_emits_phase_progress(
        self, conn, monkeypatch, tmp_path, capsys
    ) -> None:
        monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
        import yoke_core.tools.atlas_render_docs as ard_mod
        monkeypatch.setattr(ard_mod, "render", lambda r: "x")
        monkeypatch.setattr(ard_mod, "is_stale", lambda root, *, body: False)
        monkeypatch.setattr(mod, "_build_audit_report", lambda: _clean_report())
        rec = RecordCollector()

        hc_atlas_integrity(conn, DoctorArgs(), rec)

        out = capsys.readouterr().out
        assert "running HC-atlas-integrity build-audit-report" in out
        assert "running HC-atlas-integrity check-doc-staleness" in out
        assert rec.results[0].result == "PASS"

    def test_client_local_cli_row_uses_permanent_boundary(
        self, conn, monkeypatch
    ) -> None:
        report = _clean_report()
        report["yoke_cli"]["rows"].append({
            "cli_form": "yoke project install",
            "function_id": "project.install",
            "cli_tokens": ["project", "install"],
            "dispatch_kind": "client_local",
        })
        report["yoke_cli"]["count"] = 3
        report["operation_tracker"]["rows"].append({
            "shell_form": "yoke project install",
            "status": "permanent",
        })
        report["help_pages"]["per_subcommand"]["project install"] = {
            "exit_code": 0,
            "body": "ok",
            "stderr": "",
        }
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "PASS", rec.results[0].detail


def test_planted_bad_taught_command_fails(conn, monkeypatch, tmp_path) -> None:
    report = _clean_report()
    report["taught_commands"] = {
        "count": 1,
        "drift_count": 1,
        "surfaces": [{
            "kind": "yoke",
            "recipe": "yoke planted bad-spelling",
            "source": "docs/commands.md",
            "line_number": 7,
            "drift_type": "taught_yoke_command_unresolved",
        }],
    }
    monkeypatch.setattr(mod, "_repo_root", lambda: tmp_path)
    import yoke_core.tools.atlas_render_docs as ard_mod
    monkeypatch.setattr(ard_mod, "render", lambda r: "x")
    monkeypatch.setattr(ard_mod, "is_stale", lambda root, *, body: False)
    monkeypatch.setattr(mod, "_build_audit_report", lambda: report)
    rec = RecordCollector()

    hc_atlas_integrity(conn, DoctorArgs(), rec)

    assert rec.results[0].result == "FAIL"
    assert "yoke planted bad-spelling" in rec.results[0].detail


class TestFailures:
    def test_wrapped_tracker_count_mismatch(self, conn, monkeypatch) -> None:
        report = _clean_report()
        # Drop one wrapped row from the tracker — count mismatch.
        report["operation_tracker"]["rows"] = report["operation_tracker"]["rows"][:1]
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "FAIL"
        assert "wrapped tracker row count" in rec.results[0].detail

    def test_wrapped_tracker_missing_from_cli(self, conn, monkeypatch) -> None:
        report = _clean_report()
        report["operation_tracker"]["rows"][0]["shell_form"] = "yoke missing adapter"
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "FAIL"
        assert "missing from the `yoke` subcommand registry" in rec.results[0].detail

    def test_cli_function_id_missing_from_registry(self, conn, monkeypatch) -> None:
        report = _clean_report()
        report["yoke_cli"]["rows"].append({
            "cli_form": "yoke phantom", "function_id": "phantom.missing.run",
            "cli_tokens": ["phantom"],
        })
        report["yoke_cli"]["count"] = 3
        # Keep tracker count parity to isolate the registry-missing failure.
        report["operation_tracker"]["rows"].append({
            "shell_form": "yoke phantom", "status": "wrapped",
        })
        report["help_pages"]["per_subcommand"]["phantom"] = {
            "exit_code": 0, "body": "ok", "stderr": "",
        }
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "FAIL"
        assert "phantom.missing.run" in rec.results[0].detail

    def test_client_local_cli_row_requires_permanent_boundary(
        self, conn, monkeypatch
    ) -> None:
        report = _clean_report()
        report["yoke_cli"]["rows"].append({
            "cli_form": "yoke project install",
            "function_id": "project.install",
            "cli_tokens": ["project", "install"],
            "dispatch_kind": "client_local",
        })
        report["yoke_cli"]["count"] = 3
        report["help_pages"]["per_subcommand"]["project install"] = {
            "exit_code": 0,
            "body": "ok",
            "stderr": "",
        }
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "FAIL"
        assert "permanent command-shaped boundary" in rec.results[0].detail

    def test_subcommand_missing_help(self, conn, monkeypatch) -> None:
        report = _clean_report()
        report["help_pages"]["per_subcommand"]["items get"] = {
            "exit_code": 0, "body": "", "stderr": "",
        }
        rec = _record(report, conn, monkeypatch)
        assert rec.results[0].result == "FAIL"
        assert "no usable text" in rec.results[0].detail

    def test_atlas_stale_fails(self, conn, monkeypatch) -> None:
        rec = _record(_clean_report(), conn, monkeypatch, atlas_stale=True)
        assert rec.results[0].result == "FAIL"
        assert "docs/atlas.md" in rec.results[0].detail

    def test_function_inventory_still_claims_empty(self, conn, monkeypatch) -> None:
        rec = _record(
            _clean_report(), conn, monkeypatch,
            fn_inv_path_exists=True,
            fn_inv_text="Registry is reachable but empty",
        )
        assert rec.results[0].result == "FAIL"
        assert "function-inventory.md" in rec.results[0].detail


class TestWarnOnAuditError:
    def test_audit_exception_warns(self, conn, monkeypatch) -> None:
        def boom():
            raise RuntimeError("audit infra busted")
        monkeypatch.setattr(mod, "_build_audit_report", boom)
        rec = RecordCollector()
        hc_atlas_integrity(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        assert "audit infra busted" in rec.results[0].detail
