"""Project Structure test-root resolution."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_project_test_roots as roots


def test_live_entries_are_normalized(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "platform")

    def _relay(_function, _payload):
        return {"entries": [{"attachment": "services/platform-svc/tests"}]}

    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        _relay,
    )
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == (
        "services/platform-svc/tests/",
    )


def test_live_empty_falls_back_only_on_a_yoke_tree(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(roots, "_try_read", lambda _project: ())
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "yoke")
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ()
    marker = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == roots.YOKE_SEEDED_TEST_ROOTS


def test_failed_read_falls_back_only_on_a_yoke_tree(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(roots, "_try_read", lambda _project: None)
    monkeypatch.setattr(roots, "default_project_for_directory", lambda _p: "yoke")
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == ()
    marker = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    roots.resolve_test_roots.cache_clear()
    assert roots.resolve_test_roots(str(tmp_path)) == roots.YOKE_SEEDED_TEST_ROOTS
