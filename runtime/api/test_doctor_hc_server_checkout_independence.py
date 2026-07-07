"""HC-server-checkout-independence: no ambient repo-root resolution server-side."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines import doctor_hc_server_checkout_independence as hc


def test_current_server_surface_is_clean() -> None:
    # Every function-call handler + the checkout-independent resolvers must be
    # free of ambient repo-root resolution.
    repo_root = find_repo_root(Path(__file__))
    assert hc.scan_for_ambient_resolution(repo_root) == []


def test_detects_ambient_resolution_in_a_module(tmp_path: Path) -> None:
    bad = tmp_path / "bad_handler.py"
    bad.write_text("import os\nroot = os.getcwd()\n", encoding="utf-8")
    findings = hc.scan_for_ambient_resolution(
        tmp_path, extra_scan_paths=["bad_handler.py"]
    )
    assert [f.relpath for f in findings] == ["bad_handler.py"]
    assert findings[0].token == "os.getcwd("


def test_detects_find_repo_root_and_git(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "from x import find_repo_root\nr = find_repo_root(p)\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text(
        "subprocess.run(['git', 'rev-parse', '--show-toplevel'])\n", encoding="utf-8"
    )
    findings = hc.scan_for_ambient_resolution(
        tmp_path, extra_scan_paths=["a.py", "b.py"]
    )
    assert {f.relpath for f in findings} == {"a.py", "b.py"}


def test_clean_module_not_flagged(tmp_path: Path) -> None:
    ok = tmp_path / "ok_handler.py"
    ok.write_text(
        "def handle(request):\n    return request.options.get('x')\n",
        encoding="utf-8",
    )
    assert (
        hc.scan_for_ambient_resolution(tmp_path, extra_scan_paths=["ok_handler.py"])
        == []
    )
