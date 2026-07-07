from __future__ import annotations

from pathlib import Path

from yoke_core.tools import product_cli_no_checkout_smoke_core as core
from yoke_core.tools import product_cli_no_checkout_smoke_steps as steps
from yoke_core.tools.checkout_clean_room_smoke_helpers import CommandResult


class FakeRunner:
    def __init__(self, responses: dict) -> None:
        self.responses = {step: list(items) for step, items in responses.items()}
        self.calls: list = []

    def __call__(self, command: list, step: str) -> CommandResult:
        argv = [str(part) for part in command]
        self.calls.append((step, argv))
        returncode, stdout, stderr = self.responses[step].pop(0)
        return CommandResult(step=step, command=argv, cwd="/fake",
                             returncode=returncode, stdout=stdout, stderr=stderr)


def test_provision_happy_path_with_fake_runner(tmp_path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    _write_product_wheels(wheel_dir)
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "yoke").write_text("#!stub\n", encoding="utf-8")
    runner = FakeRunner({steps.STEP_WHEEL_INSTALL: [(0, "", "")] * 4})

    entry = core.provision(
        runner, source_root=_source_root(tmp_path), python=Path("python3"),
        venv_dir=venv_dir, wheel_dir=wheel_dir,
    )

    assert entry["status"] == steps.STATUS_PASS
    assert entry["evidence"]["wheel"] == "yoke_cli-0.1.0-py3-none-any.whl"
    assert entry["evidence"]["product_wheels"] == [
        "yoke_cli-0.1.0-py3-none-any.whl",
        "yoke_contracts-0.1.0-py3-none-any.whl",
        "yoke_harness-0.1.0-py3-none-any.whl",
    ]
    assert len(runner.calls) == 4


def test_provision_fails_loud_on_wheel_build_failure(tmp_path) -> None:
    runner = FakeRunner({steps.STEP_WHEEL_INSTALL: [(1, "", "no backend")]})

    entry = core.provision(
        runner, source_root=_source_root(tmp_path), python=Path("python3"),
        venv_dir=tmp_path / "venv", wheel_dir=tmp_path / "wheels",
    )

    assert entry["status"] == steps.STATUS_FAIL
    assert len(runner.calls) == 1


def test_provision_requires_product_wheels(tmp_path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    (wheel_dir / "yoke-0.1.0-py3-none-any.whl").write_bytes(b"")
    runner = FakeRunner({steps.STEP_WHEEL_INSTALL: [(0, "", "")]})

    entry = core.provision(
        runner, source_root=_source_root(tmp_path), python=Path("python3"),
        venv_dir=tmp_path / "venv", wheel_dir=wheel_dir,
    )

    assert entry["status"] == steps.STATUS_FAIL
    assert entry["evidence"]["wheel"] is None
    assert entry["evidence"]["product_wheels"] == []
    assert any("yoke-cli" in failure for failure in entry["failures"])


def _source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "source"
    for package in ("yoke-contracts", "yoke-cli", "yoke-harness"):
        package_root = source_root / "packages" / package
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return source_root


def _write_product_wheels(wheel_dir: Path) -> None:
    for name in (
        "yoke_cli-0.1.0-py3-none-any.whl",
        "yoke_contracts-0.1.0-py3-none-any.whl",
        "yoke_harness-0.1.0-py3-none-any.whl",
    ):
        (wheel_dir / name).write_bytes(b"")
