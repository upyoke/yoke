"""A published engine artifact must be able to birth a universe that serves.

Creating a database is the most catastrophic thing the engine does and the
thing it can least see from inside its own working tree. The tests beside this
one converge a schema the test process already imported; they answer whether
the convergence logic is right, and they answered yes for a build that could
not birth anything at all.

Two properties separate this from those neighbours, and both are what make it
worth its runtime.

It runs the code a release publishes rather than the code in the tree. The
wheel is what every consumer installs, and the two can disagree about facts
that only exist once the source has been packaged and moved.

And it unpacks that wheel where consumers actually keep one: inside a project
checkout, which is where a virtualenv lives. The engine asks Git whether an
installed migration entry has been released yet, and a checkout that has never
tracked the installed file answers exactly as a brand-new entry would. Reading
that answer as "no release carries this" refused boot for every install whose
packages landed under a checkout — while the published wheel demonstrably
contained the entry, and while every test in this tree passed.

The assertions are deliberately the ones a deploy gate makes rather than a
private restatement of them: the same health payload the container answers
with, read through the same shared readiness contract.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.api.health_payload_contract import migration_readiness_problem
from yoke_core.api.repo_root import find_repo_root
from yoke_core.domain import db_backend

#: The distribution that carries the engine, named as the release build names
#: it — this test is only meaningful against the artifact a release publishes.
ENGINE_PACKAGE = "yoke-core"

#: Birth the universe exactly as a container boot does, then ask the running
#: build what it can serve. Runs from the unpacked wheel, so it may import
#: nothing from the checkout that built it.
_BIRTH_UNIVERSE = '''\
"""Birth a universe through the boot path and ask it what it can serve."""

import json
import sys
from pathlib import Path

from yoke_core.api import server_entrypoint

report = Path(sys.argv[1])
if server_entrypoint.universe_is_born():
    raise SystemExit("target database already carries a universe")
server_entrypoint.birth_universe()

# Loaded after the birth, in the order the boot loads them: the container
# hands the application to uvicorn only once the universe it serves exists.
from fastapi.testclient import TestClient  # noqa: E402
from yoke_core.api.main import app  # noqa: E402

response = TestClient(app).get("/v1/health")
report.write_text(
    json.dumps(
        {
            "engine_origin": server_entrypoint.__file__,
            "status_code": response.status_code,
            "health": response.json() if response.status_code == 200 else {},
        }
    ),
    encoding="utf-8",
)
'''


def test_a_published_engine_artifact_births_a_universe_that_can_serve(
    tmp_path: Path,
) -> None:
    engine = _installed_engine(tmp_path)
    database = pg_testdb.create_test_database()
    try:
        report = _birth_universe(
            engine, pg_testdb.dsn_for_test_database(database), tmp_path
        )
    finally:
        pg_testdb.drop_test_database(database)

    # The artifact, not the tree that built it: without this the whole test
    # can quietly degrade into one more working-tree convergence check.
    assert report["engine_origin"].startswith(f"{engine}{os.sep}"), report[
        "engine_origin"
    ]
    assert report["status_code"] == 200
    health = report["health"]
    assert health["schema_ready"] is True, health["schema_missing_tables"]
    assert health["pending_migrations"] == []
    assert migration_readiness_problem(health, require_current=True) == ""


def _installed_engine(root: Path) -> Path:
    """Publish the engine wheel and unpack it where a consumer keeps one."""
    wheelhouse = _build_engine_wheelhouse(root / "wheelhouse")
    wheels = sorted(wheelhouse.glob("*.whl"))
    assert len(wheels) == 1, [wheel.name for wheel in wheels]
    site_packages = _consumer_checkout(root / "consumer") / ".venv" / "site-packages"
    site_packages.mkdir(parents=True)
    with zipfile.ZipFile(wheels[0]) as archive:
        archive.extractall(site_packages)
    return site_packages


def _build_engine_wheelhouse(wheelhouse: Path) -> Path:
    """Build the engine wheel the way the release build does."""
    uv = os.environ.get("YOKE_UV") or shutil.which("uv")
    if not uv:
        pytest.skip("uv builds the engine wheel; install uv or set YOKE_UV")
    _run(
        [
            uv,
            "build",
            "--wheel",
            "--package",
            ENGINE_PACKAGE,
            "--out-dir",
            str(wheelhouse),
            "--directory",
            str(find_repo_root(Path(__file__))),
            "--no-progress",
        ]
    )
    return wheelhouse


def _consumer_checkout(root: Path) -> Path:
    """A project checkout with history, which is where a virtualenv lives.

    The commit is the point rather than scenery. The engine answers "has this
    entry been released?" from when Git first saw the file, and a repository
    with no commits at all cannot be asked at all — so an empty one would take
    a different path than any real consumer's checkout does.
    """
    root.mkdir(parents=True)
    _run(["git", "init", "--quiet", str(root)])
    (root / "README.md").write_text("a project that installs Yoke\n", encoding="utf-8")
    _run(["git", "-C", str(root), "add", "README.md"])
    _run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=consumer@example.invalid",
            "-c",
            "user.name=consumer",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--message",
            "the history every real checkout has",
        ]
    )
    return root


def _birth_universe(site_packages: Path, dsn: str, root: Path) -> dict:
    """Run the boot path under *site_packages* against an empty *dsn*."""
    script = root / "birth_universe.py"
    script.write_text(_BIRTH_UNIVERSE, encoding="utf-8")
    report = root / "birth-report.json"
    env = dict(os.environ)
    # Ahead of everything, including whatever bound this test process to the
    # checkout's sources: the artifact answers or the test is worthless.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(site_packages), *filter(None, [env.get("PYTHONPATH", "")])]
    )
    env[db_backend.PG_DSN_ENV] = dsn
    _run([sys.executable, str(script), str(report)], env=env)
    return json.loads(report.read_text(encoding="utf-8"))


def _run(command: list, env: dict | None = None) -> None:
    done = subprocess.run(command, env=env, capture_output=True, text=True)
    assert done.returncode == 0, (
        f"{command[0]} exited {done.returncode}\n{done.stdout}\n{done.stderr}"
    )
