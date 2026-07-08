"""Core-less ``yoke board rebuild`` capability smoke.

Proves a product-wheel install (no ``yoke_core`` on the path) can run
``yoke board rebuild`` end to end: fetch the recorded ``board.data.get``
payload over the CLI transport, render with the pure ``yoke_contracts.board``
renderer, and write ``.yoke/BOARD.md``.

The recorded payload is captured once in the parent process (where
``yoke_core`` is available) against a disposable board DB, then replayed inside
a subprocess that:
  * runs from a src-only ``PYTHONPATH`` (no repo-root editable installs), and
  * installs a ``find_spec`` finder that makes ``yoke_core`` / ``runtime`` /
    ``psycopg`` unimportable,
so any accidental ``yoke_core`` reach-in in the rebuild path fails loudly
rather than silently leaning on the source-dev tier.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from runtime.api.product_boundary_isolation import write_sitecustomize


REPO_ROOT = Path(__file__).resolve().parents[2]

PACKAGE_SRC = {
    "yoke_contracts": REPO_ROOT / "packages" / "yoke-contracts" / "src",
    "yoke_cli": REPO_ROOT / "packages" / "yoke-cli" / "src",
    "yoke_harness": REPO_ROOT / "packages" / "yoke-harness" / "src",
}


class _EmptyBoardDB:
    """Fake BoardDB seam: an all-empty board with no Postgres connection.

    ``collect_board_data`` runs the full ``_assemble`` query plan against this
    handle (wrapped in ``RecordingBoardDB``), capturing a complete,
    self-consistent empty-board payload that replays without a parity miss — the
    same shape ``test_parity_empty_board`` renders for a real empty DB.
    """

    def query(self, sql, params=None):
        return []

    def query_quiet(self, sql, params=None):
        return []

    def scalar(self, sql, params=None):
        return 0


def _capture_empty_board_payload(repo_root_token: str) -> dict:
    """Capture a real ``board.data.get`` payload (parent process, core present).

    Uses the same query-shaping inputs the core-less rebuild will compute for
    ``repo_root_token`` — default board config, no vision entries — so the
    recorded plan replays without a parity miss. No Postgres: the query plan is
    recorded against an all-empty fake DB seam.
    """
    from yoke_contracts.board.config import parse_config
    from yoke_core.board.data import collect_board_data

    config = parse_config(None, repo_root=repo_root_token)
    payload = collect_board_data(
        _EmptyBoardDB(),
        scope="yoke",
        config=config,
        repo_root=repo_root_token,
        vision_entries=[],
    )
    # Prove transport fidelity in the bargain: everything survives JSON.
    return json.loads(json.dumps(payload))


def test_board_rebuild_runs_without_yoke_core(tmp_path: Path) -> None:
    checkout = tmp_path / "managed-project"
    (checkout / ".yoke").mkdir(parents=True)
    repo_root_token = str(checkout)

    payload = _capture_empty_board_payload(repo_root_token)
    payload_file = tmp_path / "board_data.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    board_path = checkout / ".yoke" / "BOARD.md"
    machine_config = tmp_path / "machine-config.json"
    # The rebuild subprocess spawns its own interpreter, so it does not inherit
    # the autouse commit-cache isolation fixture. Pin its cache_dir under tmp so
    # any commit-cache touch during the render stays off the real ~/.yoke/cache.
    machine_config.write_text(json.dumps({
        "cache_dir": str(tmp_path / "cache"),
        "projects": {
            str(checkout): {
                "project_id": 37,
                "board": {"scope": "yoke"},
            },
        },
    }), encoding="utf-8")

    code = """
import importlib.abc
import json
import os
import sys
from pathlib import Path


class CoreBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ("yoke_core", "runtime.api", "runtime.harness", "psycopg"):
            if fullname == prefix or fullname.startswith(prefix + "."):
                raise ModuleNotFoundError(
                    f"core-less smoke blocks {fullname!r}", name=fullname
                )
        return None


sys.meta_path.insert(0, CoreBlocker())

# Sanity: the source-dev tier is genuinely unreachable in this subprocess.
import importlib.util  # noqa: E402
try:
    importlib.util.find_spec("yoke_core")
    raise AssertionError("expected yoke_core to be unimportable")
except ModuleNotFoundError:
    pass

from yoke_contracts.api.function_call import (  # noqa: E402
    FunctionCallResponse,
)
from yoke_cli.transport import dispatcher as _dispatcher  # noqa: E402
import yoke_cli.board.rebuild as rebuild_mod  # noqa: E402

payload = json.loads(Path(os.environ["BOARD_PAYLOAD_FILE"]).read_text("utf-8"))
recorded = []


def _fake_call_dispatcher(*, function_id, target, payload=None, **_kwargs):
    recorded.append(function_id)
    assert function_id == "board.data.get", function_id
    return FunctionCallResponse(
        success=True,
        function=function_id,
        version="v1",
        request_id=None,
        result=payload_result,
    )


payload_result = payload
# The rebuild fetches board.data.get over the CLI's own transport; stub it to
# the recorded payload so the subprocess needs no live server.
_dispatcher.call_dispatcher = _fake_call_dispatcher

result = rebuild_mod.rebuild(
    repo_arg=os.environ["BOARD_REPO_ROOT"],
    force=True,
    scope="yoke",
)

assert result.status == "rebuilt", (result.status, result.message)
assert result.exit_code == 0, result.message
assert recorded == ["board.data.get"], recorded

board_path = Path(os.environ["BOARD_PATH"])
assert board_path.is_file(), "BOARD.md was not written"
text = board_path.read_text("utf-8")
assert "<!-- YOKE:BOARD:START" in text
assert "<!-- YOKE:BOARD:END" in text
assert "THE BOARD" in text  # header art stats box renders

ts_file = Path(str(board_path) + ".ts")
assert ts_file.is_file(), "BOARD.md timestamp sidecar was not written"

leaked = sorted(
    name for name in sys.modules
    if name == "yoke_core" or name.startswith("yoke_core.")
)
assert leaked == [], "yoke_core was imported: " + ", ".join(leaked)

print(json.dumps({"status": result.status, "board_path": str(board_path)}))
"""

    env = _core_less_env(tmp_path)
    env.update({
        "BOARD_PAYLOAD_FILE": str(payload_file),
        "BOARD_REPO_ROOT": repo_root_token,
        "BOARD_PATH": str(board_path),
        "YOKE_MACHINE_CONFIG_FILE": str(machine_config),
    })
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"core-less rebuild subprocess failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    emitted = json.loads(result.stdout.strip().splitlines()[-1])
    assert emitted["status"] == "rebuilt"
    assert board_path.is_file()
    assert "<!-- YOKE:BOARD:START" in board_path.read_text("utf-8")


def _core_less_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(
                write_sitecustomize(
                    tmp_path,
                    repo_root=REPO_ROOT,
                    allowed_repo_paths=PACKAGE_SRC.values(),
                )
            ),
            *(str(src) for src in PACKAGE_SRC.values()),
        )
    )
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("YOKE_MACHINE_CONFIG_FILE", None)
    env.pop("YOKE_ENV", None)
    return env
