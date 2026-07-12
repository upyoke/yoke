"""Parse the tracked installer campaign catalog and its GitHub companion."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


GITHUB_APP_CATALOG_NAME = "installer-github-app-testing.md"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    wave: str
    host_profile: str
    flow: str
    assertions: str


def load_scenarios_from_plan(plan_path: Path) -> list[Scenario]:
    """Extract scenario tables from the main guide and GitHub companion."""
    catalog_paths = [plan_path]
    github_catalog = plan_path.parent / GITHUB_APP_CATALOG_NAME
    if plan_path.name == "INSTALLER-TESTING.md" and github_catalog.is_file():
        catalog_paths.append(github_catalog)

    scenarios = [
        scenario
        for catalog_path in catalog_paths
        for scenario in _load_catalog(catalog_path)
    ]
    _validate_catalog(scenarios)
    return scenarios


def _load_catalog(path: Path) -> list[Scenario]:
    lines = path.read_text(encoding="utf-8").splitlines()
    scenarios: list[Scenario] = []
    current_wave = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("### Wave "):
            current_wave = _clean_cell(line.removeprefix("### "))
            index += 1
            continue
        if current_wave and _is_scenario_header(line):
            header = [_clean_cell(cell).lower() for cell in _split_table_row(line)]
            id_index = header.index("id")
            profile_index = (
                header.index("profile") if "profile" in header else header.index("host")
            )
            flow_index = header.index("flow")
            assertions_index = header.index("assertions")
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                cells = _split_table_row(lines[index])
                if len(cells) >= len(header):
                    scenario_id = _strip_code(_clean_cell(cells[id_index]))
                    if re.fullmatch(r"[A-Z][A-Z0-9-]+-\d{3}", scenario_id):
                        scenarios.append(
                            Scenario(
                                scenario_id=scenario_id,
                                wave=current_wave,
                                host_profile=_strip_code(
                                    _clean_cell(cells[profile_index])
                                ),
                                flow=_clean_cell(cells[flow_index]),
                                assertions=_clean_cell(cells[assertions_index]),
                            )
                        )
                index += 1
            continue
        index += 1
    return scenarios


def _is_scenario_header(line: str) -> bool:
    if not line.lstrip().startswith("|"):
        return False
    cells = [_clean_cell(cell).lower() for cell in _split_table_row(line)]
    return (
        "id" in cells
        and ("profile" in cells or "host" in cells)
        and "flow" in cells
        and "assertions" in cells
    )


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _clean_cell(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value)
    value = re.sub(r"\s+", " ", value.replace("**", ""))
    return value.strip()


def _strip_code(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def _validate_catalog(scenarios: Sequence[Scenario]) -> None:
    if not scenarios:
        raise ValueError("no scenario tables found")
    counts = Counter(scenario.scenario_id for scenario in scenarios)
    duplicates = sorted(
        scenario_id for scenario_id, count in counts.items() if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate scenario ids: {', '.join(duplicates)}")
