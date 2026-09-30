"""Read deployed documents and prove their authored fields reach card projections."""

from __future__ import annotations

import argparse
import subprocess
from urllib.parse import urlsplit

from yoke_contracts.project_contract.strategy_doc_fields import (
    normalize_fields,
    read_field,
)
from yoke_core.domain.json_helper import dumps_pretty, loads_text


def _command(environment: str, *arguments: str) -> str:
    result = subprocess.run(
        ["yoke", "--env", environment, *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout


def _read(environment: str, *arguments: str) -> dict:
    envelope = loads_text(_command(environment, *arguments, "--json"))
    if not isinstance(envelope, dict) or not envelope.get("success"):
        raise ValueError(f"registered read refused: {envelope}")
    return envelope["result"]


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("deployment QA requires an HTTPS target")
    return parsed.scheme, parsed.netloc


def verify_target(environment: str, base_url: str) -> None:
    """Refuse a named connection that does not serve the runner's target."""
    rows = _command(environment, "env", "list").splitlines()
    match = next(
        (row.split("|") for row in rows if row.startswith(environment + "|")), None
    )
    if match is None or len(match) != 5 or match[2] != "https":
        raise ValueError(f"{environment}: no registered HTTPS connection")
    if _origin(match[4]) != _origin(base_url):
        raise ValueError("registered connection does not match BASE_URL")


def verify_project(environment: str, project: str) -> list[dict]:
    cards = _read(environment, "strategy", "surface", "list", "--project", project)
    results = []
    for card in cards["docs"]:
        if card["archived"]:
            continue
        slug = card["slug"]
        document = _read(
            environment, "strategy", "doc", "get", slug, "--project", project
        )
        content = document["content"]
        if normalize_fields(content) != content:
            raise ValueError(f"{project}/{slug}: fields are not normalized")
        for name in ("Summary", "State"):
            if card[name.lower()] != read_field(content, name):
                raise ValueError(
                    f"{project}/{slug}: {name} card differs from stored text"
                )
        results.append(
            {
                "project": project,
                "slug": slug,
                "summary": card["summary"],
                "state": card["state"],
            }
        )
    if not results:
        raise ValueError(f"{project}: no active strategy documents verified")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project", action="append", required=True)
    arguments = parser.parse_args()
    verify_target(arguments.env, arguments.base_url)
    results = []
    for project in arguments.project:
        results.extend(verify_project(arguments.env, project))
    print(dumps_pretty({"verified_documents": len(results), "documents": results}))


if __name__ == "__main__":
    main()
