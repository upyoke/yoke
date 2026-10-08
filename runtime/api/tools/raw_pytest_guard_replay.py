"""Replay retained full shell payloads through pure baseline/candidate guards.

Never runs archived commands, hooks, emitters, or transports. The baseline is
extracted from a verified repository revision; missing originals are explicitly
inconclusive. Expected classifications must be independently supplied.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

from yoke_core.domain import lint_raw_pytest_full_suite as candidate

_DOMAIN = "packages/yoke-core/src/yoke_core/domain/"


def baseline_classifier(root: Path, revision: str):
    """Compile only verified pure parser definitions, excluding hook I/O."""
    functions = {
        "_leading_program",
        "mask_quoted_spans",
        "_unquoted_chars",
        "mask_data_sink_lines",
        "strip_heredoc_bodies",
        "_consume_heredoc",
        "_pytest_tokens",
        "_pytest_paths",
        "_classify",
    }
    namespace = {
        "re": re,
        "List": list,
        "Optional": __import__("typing").Optional,
        "Sequence": __import__("typing").Sequence,
        "Tuple": __import__("typing").Tuple,
        "WATCH_CLI_TOKENS": {},
        "cli_form": lambda module: module,
        "full_sweep_anchors": candidate.full_sweep_anchors,
    }
    from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form

    namespace.update(WATCH_CLI_TOKENS=WATCH_CLI_TOKENS, cli_form=cli_form)
    for name in (
        "lint_raw_pytest_full_suite_shell.py",
        "lint_raw_pytest_full_suite.py",
    ):
        source = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{revision}:{_DOMAIN}{name}"],
            text=True,
        )
        tree = ast.parse(source)
        tree.body = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            or isinstance(node, ast.FunctionDef)
            and node.name in functions
        ]
        exec(compile(tree, name, "exec"), namespace)
    return namespace["_classify"]


def replay(rows: list[dict], baseline):
    """Compare decisions without asserting missing evidence as passing."""
    results = []
    for row in rows:
        original = row.get("original")
        result = {key: value for key, value in row.items() if key != "original"}
        if original is None:
            result.update(verdict="inconclusive", reason="full original unavailable")
        else:
            before = baseline(original)
            after = candidate._classify(original)
            expected = row.get("expected")
            observed = after[0] if after else "silent"
            result.update(
                baseline=before,
                candidate=after,
                changed=before != after,
                verdict="inconclusive"
                if expected is None
                else "pass"
                if expected == observed
                else "fail",
            )
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--baseline-ref")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.acceptance:
        search = "rg -n 'timeout-minutes|pytest|run_tests|node|ruff' file"
        raw = "pytest " + " ".join(candidate.full_sweep_anchors())

        def evaluate(command):
            return candidate.evaluate_payload(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
            )

        harmless, controlled = evaluate(search), evaluate(raw)
        if harmless is not None or controlled is None or controlled[0] != "deny":
            raise SystemExit(
                "raw_pytest_acceptance_failed: inspect candidate guard and project lint mode"
            )
        print(
            json.dumps(
                {
                    "guard_module": candidate.__file__,
                    "search": "silent",
                    "raw_tests": controlled[2],
                    "tests_executed": False,
                }
            )
        )
        return 0
    if not all((args.baseline_ref, args.corpus, args.output)):
        parser.error("replay requires --baseline-ref, --corpus and --output")
    root = Path(__file__).resolve().parents[3]
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", f"{args.baseline_ref}^{{commit}}"],
        text=True,
    ).strip()
    corpus = json.loads(args.corpus.read_text())
    result = {
        "baseline_sha": revision,
        "candidate_sha": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        "window": corpus["window"],
        "candidate_dirty": bool(
            subprocess.check_output(
                ["git", "-C", str(root), "status", "--porcelain"],
                text=True,
            ).strip()
        ),
        "rows": replay(corpus["rows"], baseline_classifier(root, revision)),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    counts = {
        verdict: sum(row["verdict"] == verdict for row in result["rows"])
        for verdict in ("pass", "fail", "inconclusive")
    }
    print(
        json.dumps(
            {
                "output": str(args.output),
                "counts": counts,
                "comparison_status": "fail"
                if counts["fail"]
                else "inconclusive"
                if counts["inconclusive"]
                else "pass",
            }
        )
    )
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
