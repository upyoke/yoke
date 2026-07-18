import io
import json
import subprocess
from pathlib import Path

from public_installer_helpers import RecordingRunner, branded_installer_glyphs as branded_installer_glyphs, load_installer, write_channel


PROD_INDEX = "https://api.upyoke.com/simple/"
PYPI_INDEX = "https://pypi.org/simple/"


def _options(installer_mod, **overrides):
    base = dict(
        channel="stable",
        version=None,
        yes=False,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_onboard=False,
    )
    base.update(overrides)
    return installer_mod.InstallOptions(**base)


def _status_ok(version: str = "0.1.0"):
    payload = json.dumps(
        {
            "ok": True,
            "runtime": {
                "package_versions": {
                    "yoke-cli": version,
                    "yoke-contracts": version,
                    "yoke-harness": version,
                    "yoke-core": version,
                },
            },
            "connection": {"client_authority": "api", "transport": "https"},
        }
    )
    return subprocess.CompletedProcess(["yoke", "status", "--json"], 0, payload, "")


def _installed_yoke_path(tmp_path: Path, monkeypatch) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    yoke_bin = bin_dir / "yoke"
    yoke_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke_bin.chmod(0o755)
    monkeypatch.setenv("XDG_BIN_HOME", str(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return str(yoke_bin)


def test_parse_args_accepts_no_onboard_flag(monkeypatch) -> None:
    installer_mod = load_installer()
    monkeypatch.delenv("YOKE_NO_ONBOARD", raising=False)

    options = installer_mod.parse_args(["--yes", "--no-onboard"])

    assert options.yes is True
    assert options.no_onboard is True


def test_install_command_uses_generated_index_config() -> None:
    installer_mod = load_installer()
    installer = installer_mod.Installer(_options(installer_mod))

    command = installer.install_command(
        "yoke-cli==1.2.3", config_path="/tmp/yoke-uv-index.toml"
    )

    assert command == [
        "uv",
        "tool",
        "install",
        "yoke-cli==1.2.3",
        "--python",
        ">=3.10",
        "--reinstall",
        "--force",
        "--with",
        "yoke-contracts==1.2.3",
        "--with",
        "yoke-harness==1.2.3",
        "--with",
        "yoke-core==1.2.3",
        "--default-index",
        PYPI_INDEX,
        "--index-strategy",
        "first-index",
        "--config-file",
        "/tmp/yoke-uv-index.toml",
    ]


def test_install_command_constrains_python_to_at_least_310() -> None:
    # The product requires Python >=3.10 (PEP 604 unions); uv must not default to
    # an older system Python — on a 3.9-only box it refuses to resolve.
    installer_mod = load_installer()
    installer = installer_mod.Installer(_options(installer_mod))

    command = installer.install_command("yoke-cli")

    assert command[command.index("--python") + 1] == ">=3.10"


def test_install_command_honors_base_url_for_index_host() -> None:
    installer_mod = load_installer()
    installer = installer_mod.Installer(
        _options(installer_mod, base_url="https://api.stage.upyoke.com")
    )

    command = installer.install_command("yoke-cli")

    assert installer._uv_index_config_text() == (
        "[[index]]\n"
        'name = "yoke-private"\n'
        "url = \"https://api.stage.upyoke.com/simple/\"\n"
        "ignore-error-codes = [403]\n"
    )
    assert command.count("--config-file") == 0
    assert command[command.index("--default-index") + 1] == PYPI_INDEX
    assert command[command.index("--index-strategy") + 1] == "first-index"


def test_uv_runner_ignores_ambient_index_configuration(monkeypatch) -> None:
    installer_mod = load_installer()
    captured = {}
    for name in installer_mod.UV_INDEX_ENV_VARS:
        monkeypatch.setenv(name, "https://ambient.example.invalid/simple/")
    monkeypatch.setenv("UNRELATED_INSTALLER_SETTING", "preserved")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(installer_mod.subprocess, "run", fake_run)

    result = installer_mod.run_command_capture(["uv", "--version"])

    assert result.returncode == 0
    assert captured["command"] == ["uv", "--version"]
    assert captured["env"]["UNRELATED_INSTALLER_SETTING"] == "preserved"
    for name in installer_mod.UV_INDEX_ENV_VARS:
        assert name not in captured["env"]


def test_dry_run_resolves_stable_channel_and_writes_nothing(tmp_path: Path) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="1.2.3")
    output = io.StringIO()
    runner = RecordingRunner()
    installer = installer_mod.Installer(
        _options(installer_mod, dry_run=True, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: None,
        stdout=output,
    )

    installer.run()

    rendered = output.getvalue()
    assert "Resolved Yoke 1.2.3" in rendered
    assert "uv tool install yoke-cli==1.2.3" in rendered
    assert "--python '>=3.10'" in rendered
    assert "--with yoke-contracts==1.2.3" in rendered
    assert "--with yoke-harness==1.2.3" in rendered
    assert "--with yoke-core==1.2.3" in rendered
    assert "--reinstall" in rendered
    assert "Dry run" in rendered
    assert runner.commands == []


def test_full_install_pins_channel_version_and_smokes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="2.0.0\n",
        responses={(yoke_bin, "status", "--json"): _status_ok("2.0.0")},
    )
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    installer.run()

    assert runner.commands[0][:4] == ["uv", "tool", "install", "yoke-cli==2.0.0"]
    assert "--reinstall" in runner.commands[0]
    assert "yoke-contracts==2.0.0" in runner.commands[0]
    assert "yoke-harness==2.0.0" in runner.commands[0]
    assert "yoke-core==2.0.0" in runner.commands[0]
    assert "--config-file" in runner.commands[0]
    assert [yoke_bin, "--version"] in runner.commands
    assert [yoke_bin, "--help"] in runner.commands
    assert [yoke_bin, "status", "--json"] in runner.commands
    rendered = output.getvalue()
    # Condensed friendly screen: one banner, one install line, one success line.
    # The shell shim owns the setup handoff, so the helper cannot claim it when
    # the wrapper suppressed onboarding.
    assert "☀ Setting up Yoke…" in rendered
    assert "☀ Yoke v2.0.0 is ready" in rendered
    assert "☀ Starting Yoke onboard…" not in rendered
    assert "Installed Yoke with uv." not in rendered
    assert "Product-boundary audit passed." not in rendered
    assert "yoke is available to this installer process." not in rendered
    assert "Resolved Yoke" not in rendered
    assert "Install command:" not in rendered


def test_full_install_audits_installed_launcher_not_stale_ambient(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="2.0.0")
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="0.1.0\n",
        responses={
            (yoke_bin, "--version"): subprocess.CompletedProcess(
                [yoke_bin, "--version"], 0, "2.0.0\n", ""
            ),
            (yoke_bin, "--help"): subprocess.CompletedProcess(
                [yoke_bin, "--help"], 0, "help", ""
            ),
            (yoke_bin, "status", "--json"): _status_ok("2.0.0"),
            ("yoke", "status", "--json"): _status_ok("0.1.0"),
        },
    )
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=release["base_url"]),
        runner=runner,
        which=lambda name: "yoke",
        stdout=output,
    )

    installer.run()

    assert [yoke_bin, "--version"] in runner.commands
    assert [yoke_bin, "status", "--json"] in runner.commands
    assert ["yoke", "--version"] not in runner.commands
    assert ["yoke", "status", "--json"] not in runner.commands
    assert "Yoke v2.0.0 is ready" in output.getvalue()


def test_installed_yoke_resolution_uses_uv_tool_bin_before_ambient(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installer_mod = load_installer()
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    yoke_bin = tool_bin / "yoke"
    yoke_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke_bin.chmod(0o755)
    monkeypatch.delenv("UV_TOOL_BIN_DIR", raising=False)
    monkeypatch.delenv("XDG_BIN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    uv_dir = subprocess.CompletedProcess(
        ["uv", "tool", "dir", "--bin"],
        0,
        f"{tool_bin}\n",
        "",
    )
    runner = RecordingRunner(
        responses={("uv", "tool", "dir", "--bin"): uv_dir},
    )
    installer = installer_mod.Installer(
        _options(installer_mod),
        runner=runner,
        which=lambda name: "/ambient/dev/yoke" if name == "yoke" else None,
    )

    assert installer._resolve_installed_yoke_bin() == str(yoke_bin)
    assert runner.commands == [["uv", "tool", "dir", "--bin"]]


def test_explicit_version_skips_channel_fetch(tmp_path: Path, monkeypatch) -> None:
    installer_mod = load_installer()
    yoke_bin = _installed_yoke_path(tmp_path, monkeypatch)
    fetched: list[str] = []
    output = io.StringIO()
    runner = RecordingRunner(
        stdout="9.9.9\n",
        responses={(yoke_bin, "status", "--json"): _status_ok("9.9.9")},
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="9.9.9", no_onboard=True),
        fetcher=lambda url: fetched.append(url) or b"{}",
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
    )

    installer.run()

    assert fetched == []
    assert runner.commands[0][:4] == ["uv", "tool", "install", "yoke-cli==9.9.9"]
    assert "yoke-contracts==9.9.9" in runner.commands[0]
    assert "yoke-harness==9.9.9" in runner.commands[0]
    assert "yoke-core==9.9.9" in runner.commands[0]
    assert "Starting Yoke onboard" not in output.getvalue()


def test_product_boundary_audit_rejects_mixed_product_versions() -> None:
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps(
            {
                "runtime": {
                    "package_versions": {
                        "yoke-cli": "2.0.0",
                        "yoke-contracts": "1.9.0",
                        "yoke-harness": "2.0.0",
                        "yoke-core": "2.0.0",
                    },
                },
                "connection": {"client_authority": "api"},
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(_options(installer_mod), runner=runner)

    try:
        installer._product_boundary_audit(expected_version="2.0.0")
    except installer_mod.InstallError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected mixed-version audit failure")
    assert "installed Yoke package versions do not match" in message
    assert "yoke-contracts=1.9.0" in message


def test_uv_install_failure_is_user_actionable(tmp_path: Path) -> None:
    installer_mod = load_installer()
    release = write_channel(tmp_path, version="1.2.3")
    runner = RecordingRunner(rc=1, stderr="uv: index not reachable")
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=release["base_url"]),
        runner=runner,
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected uv install failure")
    assert "uv tool install" in message
    assert "configured Yoke package index and public PyPI" in message
    assert PYPI_INDEX in message
    assert "uv: index not reachable" in message
    # Smoke never ran after a failed install: only the install command issued.
    assert len(runner.commands) == 1


def test_uv_install_failure_redacts_index_credentials(tmp_path: Path) -> None:
    installer_mod = load_installer()
    secret = "synthetic-index-password"
    base_url = f"https://installer-user:{secret}@example.invalid"
    output = io.StringIO()
    runner = RecordingRunner(
        rc=1,
        stderr=(
            "failed to fetch "
            f"https://installer-user:{secret}@example.invalid/simple/yoke-cli/"
        ),
    )
    installer = installer_mod.Installer(
        _options(installer_mod, base_url=base_url, version="1.2.3"),
        runner=runner,
        stdout=output,
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected uv install failure")

    rendered = output.getvalue()
    assert secret not in message
    assert secret not in rendered
    assert "installer-user" not in message
    assert "installer-user" not in rendered
    assert "https://example.invalid/simple/yoke-cli/" in message
    assert "curl -fsSL https://example.invalid/install | bash" in rendered


def test_public_index_failure_names_both_owned_sources(tmp_path: Path) -> None:
    installer_mod = load_installer()
    output = io.StringIO()
    runner = RecordingRunner(
        rc=1,
        stderr="connection refused: https://pypi.org/simple/pydantic/",
    )
    installer = installer_mod.Installer(
        _options(installer_mod, version="1.2.3"),
        runner=runner,
        stdout=output,
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected public index failure")

    assert "configured Yoke package index and public PyPI" in message
    assert "https://pypi.org/simple/pydantic/" in message
    assert "Couldn't install Yoke" in output.getvalue()


def test_channel_missing_version_pin_fails(tmp_path: Path) -> None:
    installer_mod = load_installer()
    channels_dir = tmp_path / "site" / "dist" / "channels"
    channels_dir.mkdir(parents=True)
    (channels_dir / "stable.json").write_text("{}", encoding="utf-8")
    installer = installer_mod.Installer(
        _options(
            installer_mod,
            base_url=tmp_path.joinpath("site").as_uri(),
            dry_run=True,
        ),
    )

    try:
        installer.run()
    except installer_mod.InstallError as exc:
        assert "missing a version pin" in str(exc)
    else:
        raise AssertionError("expected missing version pin failure")


def test_product_boundary_audit_accepts_installed_engine() -> None:
    # The engine ships on every machine; an importable yoke_core is expected.
    # The audit only rejects the client wielding source-dev/admin authority.
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps(
            {
                "runtime": {"imports": {"yoke_core": {"available": True}}},
                "connection": {"client_authority": "api"},
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(_options(installer_mod), runner=runner)

    installer._product_boundary_audit()

    assert runner.commands == [["yoke", "status", "--json"]]


def test_product_boundary_audit_rejects_source_dev_authority() -> None:
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps({"connection": {"client_authority": "source-dev/admin"}}),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(_options(installer_mod), runner=runner)

    try:
        installer._product_boundary_audit()
    except installer_mod.InstallError as exc:
        assert "product-boundary audit failed" in str(exc)
        assert "source-dev/admin" in str(exc)
    else:
        raise AssertionError("expected product-boundary audit failure")


def test_advise_path_points_at_yoke_path_fix() -> None:
    installer_mod = load_installer()
    output = io.StringIO()
    installer = installer_mod.Installer(
        _options(installer_mod),
        which=lambda name: None,
        stdout=output,
    )

    installer._advise_path()

    assert "yoke path fix" in output.getvalue()
