"""Replay retained full shell payloads through baseline and candidate guards.

Never runs archived commands, hooks, emitters, or transports. The baseline is
the guard's ``_classify`` imported, in a separate interpreter, from a
``git archive`` of a verified repository revision; missing originals are
explicitly inconclusive. Expected classifications must be independently
supplied.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

from yoke_core.domain import lint_raw_pytest_full_suite as candidate

_PACKAGES = ("yoke-contracts", "yoke-core")
_BASELINE_RUNNER = """
import json, sys
sys.path[:0] = sys.argv[1:]
from yoke_core.domain.lint_raw_pytest_full_suite import _classify
commands = json.load(sys.stdin)
json.dump([_classify(command) for command in commands], sys.stdout)
"""


def baseline_classifications(root: Path, revision: str, commands: list[str]) -> list:
    """Classify ``commands`` with the guard exactly as ``revision`` shipped it."""
    archive = subprocess.check_output(
        ["git", "-C", str(root), "archive", revision, *(f"packages/{p}/src" for p in _PACKAGES)]
    )
    with tempfile.TemporaryDirectory() as tree:
        with tarfile.open(fileobj=BytesIO(archive)) as bundle:
            bundle.extractall(tree, filter="data")
        sources = [str(Path(tree, "packages", p, "src")) for p in _PACKAGES]
        output = subprocess.run(
            [sys.executable, "-I", "-c", _BASELINE_RUNNER, *sources],
            input=json.dumps(commands),
            capture_output=True,
            text=True,
            check=False,
        )
    if output.returncode != 0:
        raise SystemExit(
            f"raw_pytest_baseline_failed: {revision} could not classify the corpus; "
            f"check the revision ships lint_raw_pytest_full_suite._classify.\n{output.stderr}"
        )
    return [tuple(value) if value else None for value in json.loads(output.stdout)]


def replay(rows: list[dict], root: Path, revision: str):
    """Compare decisions without asserting missing evidence as passing."""
    originals = [row["original"] for row in rows if row.get("original") is not None]
    baseline = iter(baseline_classifications(root, revision, originals))
    results = []
    for row in rows:
        original = row.get("original")
        result = {key: value for key, value in row.items() if key != "original"}
        if original is None:
            result.update(verdict="inconclusive", reason="full original unavailable")
        else:
            before = next(baseline)
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
        if harmless is not None or controlled is None or controlled[1] != "denied":
            raise SystemExit(
                "raw_pytest_acceptance_failed: inspect candidate guard"
            )
        print(
            json.dumps(
                {
                    "guard_module": candidate.__file__,
                    "search": "silent",
                    "raw_tests": controlled[1],
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
        "rows": replay(corpus["rows"], root, revision),
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
