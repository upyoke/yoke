"""An installed candidate wheel reports controlled TLS failures without retries."""

from __future__ import annotations

from pathlib import Path

from runtime.api.product_boundary_isolation import write_sitecustomize
from test_yoke_cli_wheel_smoke import _product_env, _run
from yoke_core.tools.build_release import create_seeded_pip_venv


PROBE = r"""
import json
import ssl
import urllib.error
from pathlib import Path
import yoke_cli
from yoke_cli.transport import https as relay
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef

assert 'site-packages' in str(Path(yoke_cli.__file__).resolve())
relay.record_outcome = lambda *args, **kwargs: None
secret = 'wheel-probe-bearer-secret'
request = FunctionCallRequest(
    function='items.get.run', request_id='controlled-certificate-probe',
    actor=ActorContext(session_id='isolated-wheel-probe'), target=TargetRef(kind='global'),
)
for wrapped in (False, True):
    opens, sleeps = [], []
    error = ssl.SSLCertVerificationError(1, 'certificate has expired ' + secret)
    error.verify_code = 10
    error.verify_message = 'certificate has expired ' + secret
    failure = urllib.error.URLError(error) if wrapped else error
    def opener(*args, **kwargs):
        opens.append(1)
        raise failure
    relay._open_function_relay = opener
    response = relay.relay_https(
        request, relay.HttpsConnection('https://controlled.example.test', secret),
        sleep=sleeps.append,
    )
    assert opens == [1] and sleeps == []
    assert not response.success
    assert 'certificate_validation_failed' in response.error.message
    assert 'certificate has expired' in response.error.message
    assert 'Renew the expired' in response.error.recovery_hint
    assert 'TLS verification enabled' in response.error.recovery_hint
    assert 'sandbox' not in response.error.recovery_hint
    assert secret not in response.model_dump_json()
print(json.dumps({'installed_module': yoke_cli.__file__, 'certificate_probe': 'pass'}))
"""


def test_installed_wheel_preserves_certificate_diagnosis(tmp_path, product_wheelhouse):
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir, system_site_packages=True)
    venv_python = venv_dir / "bin" / "python"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
    sitecustomize_dir = write_sitecustomize(
        tmp_path,
        repo_root=Path(__file__).resolve().parents[2],
        allowed_repo_paths=(),
    )
    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    result = _run(
        [str(venv_python), "-c", PROBE],
        cwd=tmp_path,
        env=_product_env(
            machine_home=machine_home,
            venv_dir=venv_dir,
            sitecustomize_dir=sitecustomize_dir,
        ),
    )
    assert '"certificate_probe": "pass"' in result.stdout
