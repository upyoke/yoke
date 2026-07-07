"""Contract tests for explicit Yoke source-dev/admin setup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for package_src in (
    REPO_ROOT / "packages" / "yoke-contracts" / "src",
    REPO_ROOT / "packages" / "yoke-cli" / "src",
):
    sys.path.insert(0, str(package_src))

from yoke_cli.main import main as yoke_main
from yoke_cli.project_install import source_dev
from yoke_cli.project_install.files import (
    MODE_COPY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)


def test_dev_setup_dry_run_detects_source_checkout_without_mutating(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checkout = _source_checkout(tmp_path)
    before = _tree_snapshot(checkout)

    exit_code = yoke_main([
        "dev",
        "setup",
        str(checkout),
        "--dry-run",
        "--json",
    ])
    captured = capsys.readouterr()

    assert exit_code == 0, (
        f"stdout:\n{captured.out}\n"
        f"stderr:\n{captured.err}"
    )
    payload = json.loads(captured.out)
    assert payload["operation"] == "dev.setup"
    assert payload["applied"] is False
    assert payload["checkout"] == {
        "path": str(checkout),
        "kind": "yoke-source",
    }
    assert payload["plan"]["owner"] == "dev.setup"
    assert payload["plan"]["install_mode"] == MODE_SOURCE_LINK
    assert payload["plan"]["detected"] == {
        "yoke_source_checkout": True,
    }
    assert [step["action"] for step in payload["plan"]["steps"]] == [
        "validate-source-checkout",
        "repair-source-links",
        "install-git-hooks",
    ]
    assert _tree_snapshot(checkout) == before


@pytest.mark.parametrize("explicit_mode", [None, MODE_COPY, MODE_SOURCE_LINK])
def test_project_install_hands_source_checkout_setup_to_dev_command(
    tmp_path: Path,
    explicit_mode: str | None,
) -> None:
    checkout = _source_checkout(tmp_path)

    with pytest.raises(ProjectInstallError) as exc_info:
        source_dev.resolve_mode(checkout, explicit_mode)

    message = str(exc_info.value)
    assert "yoke dev setup" in message
    assert "source-link" in message


def test_project_install_auto_mode_stays_copy_for_external_projects(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "external-project"
    checkout.mkdir()

    mode, reason = source_dev.resolve_mode(checkout, explicit=None)

    assert mode == MODE_COPY
    assert reason == "external project repo"


def _source_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "yoke-source"
    (checkout / "runtime" / "harness").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        "[project]\nname = \"yoke\"\n",
        encoding="utf-8",
    )
    return checkout.resolve()


def _tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append(("dir", rel, ""))
        else:
            snapshot.append(("file", rel, path.read_text("utf-8")))
    return snapshot
