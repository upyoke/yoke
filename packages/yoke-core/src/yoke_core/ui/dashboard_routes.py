"""Published dashboard paths, derived from the browser's destination roster."""

from __future__ import annotations
import argparse
from functools import lru_cache
from importlib.resources import files
import json
from pathlib import Path
import subprocess

UI_REL = Path("packages/yoke-core/src/yoke_core/ui")
CONTRACT_NAME = "dashboard-routes.json"


@lru_cache(maxsize=1)
def load_dashboard_routes() -> dict:
    contract = json.loads(
        files(__package__).joinpath("contracts", CONTRACT_NAME).read_text()
    )
    if contract.get("schemaVersion") != 1 or not contract.get("views"):
        raise ValueError(
            "dashboard_routes_invalid: reinstall the matching Yoke product wheel"
        )
    return contract


def is_dashboard_path(path: str) -> bool:
    if path == "/":
        return True
    parts = path.strip("/").split("/")
    contract = load_dashboard_routes()
    if parts[0] not in contract["views"]:
        return False
    tabs = contract["tabs"].get(parts[0], [])
    max_parts = 3 if len(parts) > 1 and parts[1] in tabs else 2
    return len(parts) <= max_parts and all(parts)


def render_contract(target_root: Path) -> str:
    source = target_root / UI_REL / "static" / "universe_destinations.js"
    code = (
        "import { NAV } from " + json.dumps(source.as_uri()) + ";"
        "console.log(JSON.stringify({views:NAV.map(row=>row.id),"
        "tabs:Object.fromEntries(NAV.filter(row=>row.tabs).map(row=>"
        "[row.id,row.tabs.map(tab=>tab.id)]))}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    roster = json.loads(result.stdout)
    return (
        json.dumps(
            {
                "schemaVersion": 1,
                "localBasePath": "",
                "hostedBasePathTemplate": "/orgs/{slug}",
                **roster,
            },
            indent=2,
        )
        + "\n"
    )


def sync(*, target_root: Path) -> None:
    from yoke_core.domain.workspace_authority import (
        assert_target_under_session_work_authority,
    )

    path = target_root / UI_REL / "contracts" / CONTRACT_NAME
    assert_target_under_session_work_authority(path)
    path.write_text(render_contract(target_root), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sync", "check"])
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args()
    path = args.target_root / UI_REL / "contracts" / CONTRACT_NAME
    rendered = render_contract(args.target_root)
    if args.command == "sync":
        sync(target_root=args.target_root)
    elif path.read_text(encoding="utf-8") != rendered:
        print(
            "dashboard_routes_drift: run yoke dev run -- python3 -m "
            "yoke_core.ui.dashboard_routes sync --target-root <checkout>"
        )
        return 1
    print("dashboard routes: in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
