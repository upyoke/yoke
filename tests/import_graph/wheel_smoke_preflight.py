"""Installed manual and automatic preflight execute without source imports."""

from pathlib import Path

from runtime.api.product_boundary_isolation import write_sitecustomize
from tests.import_graph.wheel_smoke_cli import _product_env, _run


CONTROLLED = r"""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
from yoke_core.tools import migration_fleet_selection as selection
from yoke_core.domain import (
    connected_env_readiness, connected_env_tunnel_coordination,
    local_universe, local_universe_autostart, migration_fleet_preflight,
    migration_preflight_receipt_store,
)
# Import the complete engine binding, including its post-convergence validators.
engine = selection._engine_tenants('fixture', 'primary')
assert engine.plan.post_converge_validator is not None
assert 'site-packages' in str(Path(selection.__file__).resolve())
selection.resolve = lambda *a, **kw: (selection.FleetTarget(
    project='fixture', model_name='primary',
    plan=SimpleNamespace(history=('0001_existing',)),
    databases=lambda dsn: ['fixture_copy'], schema_shape_digest=lambda: 'a' * 64,
), '')
migration_preflight_receipt_store.read_declared_admin_connection = (
    lambda **kw: ('disposable-admin', '')
)
connected_env_readiness.activate_selected_postgres = lambda env: SimpleNamespace(
    dsn='host=controlled.invalid dbname=postgres', environment=env,
)
local_universe.ensure_engine_binaries = lambda emit: Path.cwd()
local_universe.cluster_spec = lambda **kw: SimpleNamespace(sock_dir=Path.cwd() / 'socket')
local_universe_autostart.ensure_running = lambda *a, **kw: None
connected_env_tunnel_coordination.use_lease_for_active_tunnel = lambda *a: nullcontext()
def rehearse(dsn_for, **kw):
    assert kw['databases'] == ['fixture_copy']
    assert 'dbname=fixture_copy' in dsn_for('fixture_copy')
    print('PASS fixture_copy controlled rehearsal', flush=True)
    return [SimpleNamespace(passed=True, database='fixture_copy', line='PASS fixture_copy')]
migration_fleet_preflight.rehearse_fleet = rehearse
if os.environ.get('PREFLIGHT_CONTROLLED_FAILURE'):
    def unavailable(*a, **kw):
        raise ImportError('controlled missing installed dependency')
    selection.resolve = unavailable
original_run = subprocess.run
def run(argv, **kw):
    if argv[:3] == ['yoke', 'projects', 'environment-settings']:
        assert kw['env']['YOKE_ENV'] == 'receipt-plane'
        if argv[3] == 'merge':
            assert '--set' in argv
            Path(os.environ['PREFLIGHT_RECEIPT_PROOF']).write_text(json.dumps(argv))
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
    return original_run(argv, **kw)
subprocess.run = run
"""


def smoke(tmp_path, product_wheelhouse, product_venv):
    isolated = write_sitecustomize(
        tmp_path,
        repo_root=Path(__file__).resolve().parents[2],
        allowed_repo_paths=(),
    )
    machine = tmp_path / "home" / ".yoke"
    machine.mkdir(parents=True)
    env = _product_env(
        machine_home=machine,
        venv_dir=product_venv,
        sitecustomize_dir=isolated,
    )
    # The only Python path addition installs the isolation guard and controlled
    # external boundaries; no product source directory is importable.
    customize = isolated / "sitecustomize.py"
    customize.write_text(customize.read_text() + "\n" + CONTROLLED)
    env["PREFLIGHT_RECEIPT_PROOF"] = str(tmp_path / "receipt.json")
    args = [
        "--project",
        "fixture",
        "rehearsal",
        "--record-receipt",
        "--product-sha",
        "b" * 40,
        "--receipt-env",
        "receipt-plane",
    ]
    for directory in (tmp_path / "platform-checkout", tmp_path / "outside-checkouts"):
        directory.mkdir()
        for automatic in (False, True):
            if automatic:
                # This is the automatic release driver's installed watcher edge.
                script = (
                    "from yoke_core.domain.deploy_pipeline_fleet_rehearsal "
                    "import _run_preflight\n"
                    f"raise SystemExit(_run_preflight({args!r}))\n"
                )
                command = [str(product_venv / "bin" / "python"), "-c", script]
            else:
                command = [
                    str(product_venv / "bin" / "yoke"),
                    "watch",
                    "preflight",
                    "--",
                    *args,
                ]
            result = _run(command, cwd=directory, env=env)
            assert "PASS fixture_copy" in result.stdout
            assert "receipt recorded on receipt-plane" in result.stdout
            proof = Path(env["PREFLIGHT_RECEIPT_PROOF"])
            assert "release.fleet_rehearsal.primary" in proof.read_text()
            proof.unlink()
    env["PREFLIGHT_CONTROLLED_FAILURE"] = "1"
    failure = _run(
        [str(product_venv / "bin" / "yoke"), "watch", "preflight", "--", *args],
        cwd=directory,
        env=env,
        check=False,
    )
    assert failure.returncode == 1
    assert "fleet_preflight_import_failed" in failure.stdout
    assert "diagnostic capture:" in failure.stdout
    assert "yoke update" in failure.stdout
    assert not Path(env["PREFLIGHT_RECEIPT_PROOF"]).exists()
