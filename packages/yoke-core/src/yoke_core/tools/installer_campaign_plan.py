"""Export and compare installer cases using a registered plan's target snapshot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from yoke_contracts.qa_case_starting_state import BASELINE
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain import pack_catalog
from yoke_cli.config import repo_upstream_git as source_git


_CASE_DEFAULTS: dict[str, Any] = {
    "case_key": None,
    "position": None,
    "method_id": None,
    "instructions": None,
    "expected_outcome": None,
    "method_config": {},
    "success_policy_id": None,
    "success_policy_params": None,
    "host_baselines": [],
    "starting_state": None,
    "starting_state_reason": None,
    "entry_surface": None,
    "required_completion": None,
}


# Plans whose cases this build generates; boot converges them when source-bound.
SOURCE_AUTHORED_PLAN_SLUGS = ("installer-campaign", "installer-exploration")


class SourceSyncRefused(ValueError):
    """The source is not proven safe for the shared saved plan."""


def _authored(case: dict[str, Any], field: str) -> Any:
    """One authored field, with a stored baseline case's normalized state.

    Authoring stores a case that names ``host_baselines`` as
    ``starting_state: "baseline"``; the source leaves it implied.
    """
    value = case.get(field, _CASE_DEFAULTS[field])
    if field == "starting_state" and value is None and case.get("host_baselines"):
        return BASELINE
    return value


def _source_cases(
    plan: dict[str, Any], primary_machine=None, joining_machine=None
) -> list[dict]:
    slug = plan["slug"]
    if slug == "installer-campaign":
        configured = {case["case_key"]: case for case in plan["cases"]}
        primary_machine = primary_machine or configured.get("path-on-shell", {}).get(
            "method_config", {}
        ).get("machine")
        joining_machine = joining_machine or configured.get(
            "second-machine-join", {}
        ).get("method_config", {}).get("machine")
        return installer_campaign_cases_for_target(
            plan["execution_target"],
            primary_machine=primary_machine,
            joining_machine=joining_machine,
        )
    if slug == "installer-exploration":
        descriptor = pack_catalog.load_pack_descriptor("machine-qa")
        version = descriptor["versions"][descriptor["latest_version"]]
        source = pack_catalog.server_tree_root() / "packs" / "machine-qa"
        return json.loads(
            (
                source / version["source"] / "qa/examples/installer-exploration.json"
            ).read_text()
        )
    raise ValueError(
        f"unsupported installer plan {slug!r}; read installer-campaign or "
        "installer-exploration with yoke qa plan get before exporting."
    )


def compare_plan(
    plan: dict[str, Any], *, primary_machine=None, joining_machine=None
) -> tuple[list[dict], dict]:
    """Compare authored fields, excluding row identity and historical proof."""
    cases = _source_cases(plan, primary_machine, joining_machine)
    installed = {case["case_key"]: case for case in plan["cases"]}
    generated = {case["case_key"]: case for case in cases}
    if len(installed) != len(plan["cases"]):
        raise ValueError("installed plan contains duplicate case keys")
    differences = []
    for key in sorted(installed.keys() | generated.keys()):
        if key not in installed or key not in generated:
            differences.append(
                {
                    "case_key": key,
                    "change": "added" if key in generated else "removed",
                }
            )
            continue
        fields = [
            field
            for field in _CASE_DEFAULTS
            if _authored(installed[key], field) != _authored(generated[key], field)
        ]
        if fields:
            differences.append({"case_key": key, "fields": fields})
    return cases, {
        "plan_id": plan["id"],
        "target_environment": plan["target_environment"],
        "case_count": len(cases),
        "matches_source": not differences,
        "differences": differences,
    }


def _remote_tracking_default_branch(root: str) -> tuple[str, str, int]:
    """Return the remote that tracks the default branch it publishes.

    Each configured remote's published default is passed to
    ``resolve_remote``, so a checkout with several remotes still names the
    one git records as tracking that branch. A single remote, or only a
    push default, keeps the same resolution as before.
    """
    listed = source_git.git(root, "remote")
    names = source_git.out(listed).split() if listed.returncode == 0 else []
    for name in names:
        published = source_git.resolve_base_branch(root, name)
        if not published:
            continue
        remote, count = source_git.resolve_remote(root, published)
        if remote == name:
            return remote, published, count
    remote, count = source_git.resolve_remote(root)
    branch = source_git.resolve_base_branch(root, remote) if remote else ""
    return remote, branch, count


def export_source_revision() -> str:
    """Only landed, clean source may feed the shared saved-plan sync."""
    root = str(pack_catalog.server_tree_root())
    recovery = (
        "sync after merge from a clean checkout of the repository's default "
        "branch; use item-scoped or run-bound correction cases for lane proof."
    )
    try:
        remote, branch, count = _remote_tracking_default_branch(root)
        if not remote or not branch:
            raise ValueError(f"default branch unavailable ({count} configured remotes)")
        fetched = source_git.fetch_branch(root, remote, branch)
        if fetched.returncode:
            raise ValueError(source_git.reason(fetched))
        head = source_git.git(root, "rev-parse", "HEAD^{commit}")
        upstream = source_git.git(
            root, "rev-parse", source_git.tracking_ref(remote, branch) + "^{commit}"
        )
        dirty = source_git.git(
            root, "status", "--porcelain", "--untracked-files=normal"
        )
        for result in (head, upstream, dirty):
            if result.returncode:
                raise ValueError(source_git.reason(result))
        if source_git.out(dirty):
            raise ValueError("source checkout has uncommitted changes")
        revision = source_git.out(head)
        ancestry = source_git.git(
            root, "merge-base", "--is-ancestor", revision, source_git.out(upstream)
        )
        if ancestry.returncode == 1:
            raise ValueError(f"source commit {revision} is not on {remote}/{branch}")
        if ancestry.returncode:
            raise ValueError(source_git.reason(ancestry))
        return revision
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SourceSyncRefused(
            f"qa_plan_source_unmerged_or_unverified: {exc}; {recovery}"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-file",
        type=Path,
        required=True,
        help="Full JSON receipt from yoke qa plan get.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        help="Export source-proven cases for qa.plan_cases.sync; sync after merge.",
    )
    parser.add_argument(
        "--primary-machine", help="Registered primary Test Machine for campaign cases."
    )
    parser.add_argument(
        "--joining-machine",
        help="Distinct registered Test Machine for the joining case.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when installed cases differ from source.",
    )
    args = parser.parse_args(argv)
    try:
        receipt = json.loads(args.plan_file.read_text())
        if receipt.get("success") is not True:
            raise ValueError("plan read did not succeed")
        source_revision = export_source_revision() if args.cases_file else None
        cases, report = compare_plan(
            receipt["result"]["plan"],
            primary_machine=args.primary_machine,
            joining_machine=args.joining_machine,
        )
        if args.cases_file:
            args.cases_file.write_text(
                json.dumps(
                    {"source_revision": source_revision, "cases": cases}, indent=2
                )
                + "\n"
            )
            report["source_revision"] = source_revision
    except SourceSyncRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            f"installer_campaign_plan_snapshot_invalid: {exc}; "
            "capture yoke qa plan get PLAN --project P --full --json "
            "again and verify its execution_target before retrying.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2))
    if args.check and not report["matches_source"]:
        print(
            "installer_campaign_plan_source_drift: installed cases differ; "
            "a source-bound plan converges when a server running a merged "
            "build that carries this source boots. For an unbound plan, or "
            "after boot logged qa_plan_source_convergence_failed: export clean "
            "merged source with --cases-file, review the differences, install "
            "with yoke qa plan-cases sync and check a fresh plan receipt.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
