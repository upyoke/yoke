"""Prove a symlinks-disabled contributor checkout before product onboarding."""

from pathlib import Path
import argparse
import os
import subprocess
import sys
import tempfile

try:
    from .product_runner_source_tests import declared_source_tests
except ImportError:
    from product_runner_source_tests import declared_source_tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    args.output.mkdir(parents=True, exist_ok=True)
    tests = declared_source_tests(root)
    with tempfile.TemporaryDirectory(prefix="yoke-contributor-", dir="/tmp" if sys.platform == "darwin" else None) as cluster:
        env = {**os.environ, "YOKE_PG_CLUSTER_ROOT": cluster, "YOKE_PYTEST_LOCAL": "1"}
        failed = True
        try:
            for label, flags in (("collection", ["--collect-only"]), ("tests", [])):
                capture = args.output / f"contributor-{label}.txt"
                print(f"contributor checkout {label}: {capture}", flush=True)
                with capture.open("w", encoding="utf-8") as stream:
                    result = subprocess.run([
                        sys.executable, "-m", "pytest", "-q", *flags, *tests,
                    ], cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
                if result.returncode:
                    print(capture.read_text(encoding="utf-8"), flush=True)
                    return result.returncode
            failed = False
            return 0
        finally:
            subprocess.run([
                sys.executable, "-m", "yoke_core.tools.pg_testcluster", "stop",
            ], cwd=root, env=env, check=not failed)


if __name__ == "__main__":
    raise SystemExit(main())
