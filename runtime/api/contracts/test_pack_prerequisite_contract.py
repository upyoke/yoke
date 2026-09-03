from __future__ import annotations

import pytest

from yoke_contracts.packs import validate_pack_prerequisites


def _pulumi() -> dict[str, object]:
    return {
        "tool": "pulumi",
        "minimum_version": "3.0.0",
        "probe": {"executable": "pulumi", "version_args": ["version"]},
        "install": {
            "darwin": "brew install pulumi/tap/pulumi",
            "linux": "curl -fsSL https://get.pulumi.com | sh",
            "windows": "winget install Pulumi.Pulumi",
        },
    }


def test_prerequisites_normalize_detached_probe_and_recipe_values() -> None:
    declaration = _pulumi()

    normalized = validate_pack_prerequisites([declaration])

    assert normalized == [declaration]
    assert normalized[0] is not declaration
    assert normalized[0]["probe"] is not declaration["probe"]
    assert normalized[0]["install"] is not declaration["install"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.pop("install"), "must declare"),
        (lambda row: row.update(tool="Pulumi CLI"), "lowercase slugs"),
        (lambda row: row.update(minimum_version="3"), "must be x.y.z"),
        (
            lambda row: row["probe"].update(version_args=[]),
            "probe is invalid",
        ),
        (
            lambda row: row["install"].pop("windows"),
            "must cover darwin, linux, and windows",
        ),
    ],
)
def test_prerequisite_contract_rejects_incomplete_or_unsafe_entries(
    mutate,
    message: str,
) -> None:
    declaration = _pulumi()
    mutate(declaration)

    with pytest.raises(ValueError, match=message):
        validate_pack_prerequisites([declaration])


def test_prerequisite_contract_rejects_repeated_tool_names() -> None:
    with pytest.raises(ValueError, match="repeated"):
        validate_pack_prerequisites([_pulumi(), _pulumi()])
