def product_spec(version: str | None) -> str:
    if version:
        return f"{PRODUCT_PACKAGE}=={version}"
    return PRODUCT_PACKAGE


def _rerun_command(base_url: str, *, channel: str | None = None) -> str:
    origin = _safe_url(base_url).rstrip("/")
    if origin == DEFAULT_BASE_URL:
        scheme, host = origin.split("://", 1)
        origin = f"{scheme}://{host.removeprefix('api.')}"
    command = f"curl -fsSL {origin}/install | sh"
    if channel is not None:
        command += f" -s -- --channel {shlex.quote(channel)}"
    return command


def _product_spec_version(spec: str) -> str | None:
    prefix = f"{PRODUCT_PACKAGE}=="
    if spec.startswith(prefix):
        version = spec[len(prefix) :].strip()
        return version or None
    return None


def _with_product_requirements(version: str | None) -> tuple[str, ...]:
    args: list[str] = []
    for package in LOCKSTEP_PRODUCT_PACKAGES:
        requirement = f"{package}=={version}" if version else package
        args.extend(["--with", requirement])
    return tuple(args)


def _verify_product_package_versions(
    runtime: object,
    expected_version: str,
) -> None:
    missing_versions = (
        "product-boundary audit failed: `yoke status --json` did not "
        "report runtime package versions."
    )
    if not isinstance(runtime, dict):
        raise InstallError(missing_versions)
    raw_versions = runtime.get("package_versions")
    if not isinstance(raw_versions, dict):
        raise InstallError(missing_versions)
    expected_packages = (PRODUCT_PACKAGE, *LOCKSTEP_PRODUCT_PACKAGES)
    mismatched = [
        f"{package}={raw_versions.get(package) or '<missing>'}"
        for package in expected_packages
        if raw_versions.get(package) != expected_version
    ]
    if mismatched:
        raise InstallError(
            "product-boundary audit failed: installed Yoke package versions "
            f"do not match channel version {expected_version}: " + ", ".join(mismatched)
        )


def _verify_product_package_presence(runtime: object) -> None:
    """Require every package needed by installed hooks and product commands."""
    if not isinstance(runtime, dict):
        raise InstallError(
            "product-boundary audit failed: `yoke status --json` did not "
            "report runtime package versions."
        )
    raw_versions = runtime.get("package_versions")
    if not isinstance(raw_versions, dict):
        raise InstallError(
            "product-boundary audit failed: `yoke status --json` did not "
            "report runtime package versions."
        )
    missing = [
        package
        for package in (PRODUCT_PACKAGE, *LOCKSTEP_PRODUCT_PACKAGES)
        if not raw_versions.get(package)
    ]
    if missing:
        raise InstallError(
            "product-boundary audit failed: installed Yoke product packages "
            "are incomplete: " + ", ".join(missing)
        )


def _display_version(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    match = _DEV_VERSION_RE.match(raw)
    if not match:
        return raw
    return f"{match.group('base')} (dev {match.group('local')})"


def _uv_reported_already_installed(
    result: subprocess.CompletedProcess[str],
) -> bool:
    blob = f"{result.stdout}\n{result.stderr}".lower()
    return any(
        text in blob
        for text in (
            "already installed",
            "nothing to do",
            "is up to date",
        )
    )


def _failure_reason(result: subprocess.CompletedProcess[str]) -> str:
    for stream in (result.stderr, result.stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            return _bounded_diagnostic(lines[-1], FAILURE_REASON_MAX_CHARS)
    return f"uv exited with status {result.returncode}."


def _release_records_url(base_url: str, version: str) -> str:
    quoted = urllib.parse.quote(version, safe="")
    return (
        f"{base_url.rstrip('/')}/{_RELEASE_RECORD_DIR}/{quoted}/"
        f"{_RELEASE_RECORD_FILENAME}"
    )


def fetch_url(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise InstallError(
            f"could not fetch {_safe_url(url)}: {_sanitize_diagnostic(str(exc))}"
        ) from exc
    except OSError as exc:
        raise InstallError(
            f"could not fetch {_safe_url(url)}: {_sanitize_diagnostic(str(exc))}"
        ) from exc


def _install_candidate(command: list[str], env: dict[str, str], root: Path, generation: Path, version: str):
    """uv owns each private tool environment; only publication changes PATH."""
    isolated = dict(env, UV_TOOL_DIR=str(generation / "tools"), UV_TOOL_BIN_DIR=str(generation / "bin"))
    result = subprocess.run(command, env=isolated, capture_output=True, text=True, check=False)
    if result.returncode:
        shutil.rmtree(generation)
        return result
    bin_dir = subprocess.run(
        ["uv", "tool", "dir", "--bin"], env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not Path(bin_dir).is_absolute():
        raise InstallError("cli_launcher_directory_unavailable: repair uv tool dir --bin and retry")
    python = generation / "tools" / "yoke-cli" / "bin" / "python3"
    runtime_script = generation / "runtime.py"
    runtime_script.write_text(CLI_RUNTIME_SOURCE, encoding="utf-8")
    activation = subprocess.run(
        [str(python), "-I", str(runtime_script), str(root), str(generation), bin_dir, version],
        env=env, capture_output=True, text=True, check=False,
    )
    return subprocess.CompletedProcess(command, activation.returncode, result.stdout + activation.stdout, result.stderr + activation.stderr)


def _run_isolated_install(command: list[str], env: dict[str, str]):
    location = subprocess.run(
        ["uv", "tool", "dir"], env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    root = Path(location) / "yoke-cli-releases"
    if not Path(location).is_absolute():
        raise InstallError("cli_release_root_unavailable: uv returned no absolute tool directory; repair uv and retry")
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    version = _product_spec_version(command[3])
    if not version or not re.fullmatch(r"[A-Za-z0-9_.+-]+", version):
        raise InstallError("cli_release_version_required: select an exact published release and retry")
    staging = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=root))
    lease = (staging / "lease").open("a+")
    fcntl.flock(lease, fcntl.LOCK_SH)
    (staging / "pending").touch()
    generation = releases / staging.name
    staging.rename(generation)
    with lease:
        try:
            result = _install_candidate(command, env, root, generation, version)
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallError(f"cli_release_install_failed: {exc}; repair uv and rerun the installer") from exc
        return result


def run_command_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in RESOLVER_SOURCE_ENV_VARS
    }
    if list(command)[:3] == ["uv", "tool", "install"]:
        try:
            return _run_isolated_install(list(command), env)
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallError(f"cli_release_install_failed: {exc}; repair uv and rerun the installer") from exc
    if list(command) == ["uv", "tool", "update-shell"]:
        uv = shutil.which("uv") or "uv"
        command = [uv, "tool", "update-shell"]
        env["PATH"] = env.pop("YOKE_INSTALL_INHERITED_PATH", env.get("PATH", ""))
    return subprocess.run(
        list(command),
        check=False,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _unexpected_status_error_codes(status: object) -> list[str]:
    if not isinstance(status, dict):
        return ["status_not_object"]
    issues = status.get("issues")
    if not isinstance(issues, list):
        return ["issues_missing"]
    unexpected: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            unexpected.append("issue_not_object")
            continue
        severity = str(issue.get("severity") or "")
        code = str(issue.get("code") or "")
        if severity == "error" and code not in FRESH_STATUS_ERROR_CODES:
            unexpected.append(code or "missing_code")
    return unexpected


def _loads_json(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise InstallError(f"{label} must be a JSON object")
    return value


def _require_channel_release_evidence(
    channel: dict[str, object],
    label: str,
) -> None:
    """Preserve historical v2 while requiring content evidence from v3."""
    schema_version = channel.get("schema_version")
    if schema_version == 2:
        return
    if schema_version != 3:
        raise InstallError(f"{label} channel has unsupported schema_version")
    migration_history = channel.get("migration_history")
    if not isinstance(migration_history, dict):
        raise InstallError(
            f"{label} channel schema v3 is missing trusted migration history evidence"
        )
    digest = str(migration_history.get("manifest_sha256") or "")
    source_commit = str(migration_history.get("source_commit") or "")
    manifest_url = str(migration_history.get("manifest_url") or "")
    evidence_url = str(migration_history.get("evidence_url") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InstallError(f"{label} channel has an invalid migration manifest digest")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise InstallError(f"{label} channel has an invalid migration source commit")
    if not manifest_url.endswith("/migration-history.json"):
        raise InstallError(f"{label} channel has an invalid migration manifest URL")
    if not evidence_url.endswith("/migration-history-record.json"):
        raise InstallError(
            f"{label} channel has an invalid migration release-evidence URL"
        )
