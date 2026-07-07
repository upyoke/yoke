"""Install-bundle fixtures for project onboarding CLI tests."""

from __future__ import annotations

import hashlib
from typing import Any


def install_bundle(project: dict[str, Any]) -> dict[str, Any]:
    strategy_body = "# Mission\n\nOperate this project through Yoke.\n"
    digest = hashlib.sha256(strategy_body.encode("utf-8")).hexdigest()
    strategy = (
        "<!-- YOKE:STRATEGY-DOC slug=MISSION "
        "updated_at=2026-06-16T00:00:00Z "
        f"content_sha256={digest} "
        "The Yoke DB is authoritative for this doc: edit the file, "
        "then write back with `yoke strategy ingest MISSION`. -->\n"
        f"{strategy_body}"
    )
    return {
        "bundle_schema": 1,
        "yoke_version": "9.9.9",
        "project_id": project["id"],
        "project_slug": project["slug"],
        "files": [{
            "path": ".codex/skills/yoke/onboard-project/SKILL.md",
            "content": "# onboard-project\n",
        }],
        "project_contract_files": [{
            "path": ".yoke/lint-config",
            "content": "lint_main_commit=deny\n",
            "install_policy": "seed_if_missing",
            "category": "project_policy",
        }],
        "strategy_files": [{
            "path": ".yoke/strategy/MISSION.md",
            "content": strategy,
            "install_policy": "db_render",
        }],
        "hooks": {},
    }


__all__ = ["install_bundle"]
