"""Tests for the project-local external artifact fetch inventory."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_external_artifact_fetches as mod


def _workflow(root: Path, body: str) -> None:
    path = root / ".github/workflows/fetch.yml"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")


def _run(root: Path, monkeypatch):
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(root))
    records = RecordCollector()
    mod.hc_external_artifact_fetch_inventory(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_declares_inventory_check() -> None:
    assert [check.slug for check in mod.PROJECT_HEALTH_CHECKS] == [
        "external-artifact-fetch-inventory"
    ]


def test_seeded_bare_curl_is_reported(monkeypatch, tmp_path: Path) -> None:
    _workflow(
        tmp_path,
        "jobs:\n  fetch:\n    steps:\n"
        "      - run: curl -fsSL https://downloads.example.test/tool.tar.gz\n",
    )

    result = _run(tmp_path, monkeypatch)

    assert result.result == "WARN"
    assert "unclassified-bare-fetch" in result.detail
    assert "curl" in result.detail
    assert ".github/workflows/fetch.yml:4" in result.detail


def test_inline_allowance_with_justification_passes(monkeypatch, tmp_path: Path) -> None:
    _workflow(
        tmp_path,
        "jobs:\n  fetch:\n    steps:\n"
        "      # artifact-fetch-allow: fixture uses a deterministic local proxy\n"
        "      - run: curl -fsSL https://downloads.example.test/tool.tar.gz\n",
    )

    result = _run(tmp_path, monkeypatch)

    assert result.result == "PASS"
    assert "allowlisted-with-justification" in result.detail
    assert "deterministic local proxy" in result.detail


def test_dockerfile_gateway_call_is_classified(monkeypatch, tmp_path: Path) -> None:
    dockerfile = tmp_path / "nested/image/Dockerfile.release"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "RUN python /app/yoke_core/domain/postgres_binaries.py\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, monkeypatch)

    assert result.result == "PASS"
    assert "gateway-fetched" in result.detail


def test_repository_inventory_has_no_unclassified_fetches() -> None:
    root = Path(__file__).resolve().parents[3]

    bare = [
        entry
        for entry in mod.inventory(root)
        if entry.classification == "unclassified-bare-fetch"
    ]

    assert bare == []


def test_inventory_skips_generated_build_dockerfiles(tmp_path: Path) -> None:
    nested = tmp_path / "build" / "bdist.linux-x86_64" / "wheel"
    nested.mkdir(parents=True)
    (nested / "Dockerfile").write_text(
        "RUN curl -fsSL https://downloads.example.test/tool.tar.gz\n",
        encoding="utf-8",
    )
    real = tmp_path / "packs" / "image" / "Dockerfile"
    real.parent.mkdir(parents=True)
    real.write_text(
        "RUN python /app/yoke_core/domain/postgres_binaries.py\n",
        encoding="utf-8",
    )

    entries = mod.inventory(tmp_path)

    assert all(not entry.path.startswith("build/") for entry in entries)
    assert any(entry.classification == "gateway-fetched" for entry in entries)


def test_inventory_skips_a_dockerfile_removed_before_read(
    tmp_path: Path, monkeypatch
) -> None:
    dockerfile = tmp_path / "app" / "Dockerfile"
    dockerfile.parent.mkdir()
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    original = Path.read_text

    def vanish(self, *args, **kwargs):
        if self == dockerfile:
            raise FileNotFoundError(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", vanish)

    assert mod.inventory(tmp_path) == []
