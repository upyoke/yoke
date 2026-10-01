"""Run source-development checks with disposable dependencies and Postgres."""

from pathlib import Path
import shutil
import sys
import tempfile


def run_source_tests(root: Path, commands) -> None:
    commands.run(
        "install-test-dependencies",
        ["uv", "sync", "--all-packages", "--all-groups", "--locked"],
        cwd=root,
    )
    # The socket must fit even when macOS's ordinary temp root is very long.
    with tempfile.TemporaryDirectory(prefix="yoke-pg-smoke-", dir="/tmp") as cluster:
        commands.env["YOKE_PG_CLUSTER_ROOT"] = cluster
        try:
            commands.run(
                "pytest-subset",
                [
                    "uv",
                    "run",
                    "--frozen",
                    "yoke",
                    "watch",
                    "pytest",
                    "--local",
                    "--",
                    "runtime/harness/test_hook_runner_decision_render.py",
                    "tests/import_graph/test_yoke_cli_dev_setup_contract.py",
                    "-q",
                ],
                cwd=root,
            )
        except Exception:
            home = Path(commands.env["YOKE_MACHINE_HOME"])
            captures = list(home.rglob("yoke-pytest.raw.*.log"))
            captures.append(Path(cluster) / "server.log")
            for capture in captures:
                if capture.is_file():
                    destination = commands.output / capture.name
                    shutil.copy2(capture, destination)
                    print(f"product-smoke diagnostic={destination}", flush=True)
            raise
        finally:
            primary_failure = sys.exc_info()[0] is not None
            try:
                commands.run(
                    "stop-test-postgres",
                    [
                        "uv",
                        "run",
                        "--frozen",
                        "python3",
                        "-m",
                        "yoke_core.tools.pg_testcluster",
                        "stop",
                    ],
                    cwd=root,
                )
            except Exception:
                if not primary_failure:
                    raise
