"""Read-only proof of deployed roster paging and instruction output."""

from __future__ import annotations

import argparse
import json
import subprocess


def read(env: str, args: list[str]) -> str:
    completed = subprocess.run(
        ["yoke", "--env", env, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"roster_read_failed: {' '.join(args)}: {completed.stderr.strip()}; "
            "restore access to the target environment and rerun this proof"
        )
    return completed.stdout


def verify(env: str, project: str) -> None:
    for args, key in [
        (["projects", "capabilities", "list"], "rows"),
        (["strategy", "surface", "list", "--project", project], "docs"),
    ]:
        page_args = [*args, "--limit", "1"]
        first = json.loads(read(env, [*page_args, "--json"]))["result"]
        assert first.get("limit") == 1, (
            "roster_paging_unserved: deploy the paging handler"
        )
        assert first.get("offset") == 0
        assert len(first[key]) <= 1
        following = first.get("next_offset")
        if following is not None:
            assert following == 1
            second = json.loads(read(env, [*page_args, "--offset", "1", "--json"]))[
                "result"
            ]
            assert second["offset"] == 1
            assert len(second[key]) == 1
            assert second[key] != first[key]
            assert "More rows. Next page:" in read(env, page_args)
        print(f"Verified {'.'.join(args[:3])}: page metadata and complete rows")

    args = ["workflow", "execution-instruction", "list"]
    rows = json.loads(read(env, [*args, "--json"]))["result"]["instructions"]
    summary = read(env, args)
    full = read(env, [*args, "--full"])
    for row in rows:
        content = str(row.get("content") or "")
        title = content.splitlines()[0] if content else ""
        assert f"{row['id']}  {title}" in summary
        assert f"## {row['id']} {title}" in full
        assert content in full
    if rows:
        assert (
            "Read them in full: yoke workflow execution-instruction list --full"
            in summary
        )
    print(
        f"Verified instruction descriptors and full headings for {len(rows)} instructions"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    verify(args.env, args.project)


if __name__ == "__main__":
    main()
