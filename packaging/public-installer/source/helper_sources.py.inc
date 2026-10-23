
# uv children create files with this umask, so fresh cache entries and tool
# environments are never group- or other-writable. The parent umask is unchanged.
CANDIDATE_UMASK = 0o022
# These two distributions own every credential-helper bundle source.
HELPER_SOURCE_PACKAGES = ("yoke-cli", "yoke-contracts")
# Runs inside the candidate: the release's own helper-bundle owner enumerates
# and safe-reads every source the credential helper copies, plus the launcher.
HELPER_SOURCE_CHECK = """
import json, os, stat
from pathlib import Path
from yoke_cli.config import github_git_credential_bundle as bundle
from yoke_cli.config import github_git_credential_launcher as launcher
paths = [source for source, _name in bundle._bundle_sources()]
paths.append(Path(launcher.__file__))
loose, refusal = [], None
for path in paths:
    try:
        bundle._safe_read_source(path)
    except bundle.GitHubCredentialBundleError as exc:
        info = os.lstat(path) if os.path.lexists(path) else None
        mode = stat.S_IMODE(info.st_mode) if info else 0
        if (
            info
            and stat.S_ISREG(info.st_mode)
            and info.st_size <= bundle.MAX_HELPER_SOURCE_BYTES
            and mode & 0o022
        ):
            loose.append(f"{path} (mode {mode:04o})")
        elif refusal is None:
            refusal = f"{path}: {exc}"
print(json.dumps({"checked": len(paths), "unsafe_permissions": loose, "refusal": refusal}))
"""


def _run_candidate_uv(command: list[str], env: dict[str, str]):
    return subprocess.run(
        command, env=env, capture_output=True, text=True, check=False,
        umask=CANDIDATE_UMASK,
    )


def _unsafe_helper_source_permissions(generation: Path, env: dict[str, str]) -> list[str]:
    """Return helper sources unsafe only by permissions; refuse anything else."""
    python = generation / "tools" / "yoke-cli" / "bin" / "python3"
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", HELPER_SOURCE_CHECK],
            env=env, capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(
            f"helper_source_check_failed: the candidate could not check its "
            f"credential-helper sources: {exc}; rerun the installer."
        ) from exc
    lines = result.stdout.strip().splitlines()
    try:
        verdict = json.loads(lines[-1]) if lines else None
    except ValueError:
        verdict = None
    if result.returncode or not isinstance(verdict, dict):
        raise InstallError(
            "helper_source_check_failed: the candidate could not check its "
            "credential-helper sources: "
            + _bounded_diagnostic(result.stderr or result.stdout, DIAGNOSTIC_MAX_CHARS)
            + "; rerun the installer."
        )
    if verdict.get("refusal"):
        raise InstallError(
            "helper_source_unsafe: a credential-helper source is not a safe regular "
            f"file: {verdict['refusal']}; repair or remove it, then rerun the installer."
        )
    return [str(path) for path in verdict.get("unsafe_permissions") or []]


def _install_qualified_candidate(command: list[str], env: dict[str, str], generation: Path):
    """Install the candidate; repair unsafe cached helper sources at most once."""
    result = _run_candidate_uv(command, env)
    if result.returncode:
        return result
    loose = _unsafe_helper_source_permissions(generation, env)
    if not loose:
        return result
    # Evict only the helper-owning packages from the cache uv just used.
    config = command[command.index("--config-file"):][:2] if "--config-file" in command else []
    clean = subprocess.run(
        ["uv", "cache", "clean", *HELPER_SOURCE_PACKAGES, *config],
        env=env, capture_output=True, text=True, check=False, umask=CANDIDATE_UMASK,
    )
    if clean.returncode:
        raise InstallError(
            "helper_source_cache_clean_failed: uv cache clean "
            + " ".join(HELPER_SOURCE_PACKAGES)
            + " failed after group- or other-writable helper sources were found ("
            + ", ".join(loose) + "): "
            + _bounded_diagnostic(clean.stderr or clean.stdout, DIAGNOSTIC_MAX_CHARS)
            + "; let other uv commands finish, then rerun the installer."
        )
    print(
        "helper_source_cache_repaired: evicted uv cache entries for "
        + ", ".join(HELPER_SOURCE_PACKAGES)
        + " because helper sources were group- or other-writable ("
        + ", ".join(loose) + "); reinstalling once.",
        file=sys.stderr,
    )
    retry = _run_candidate_uv(command, env)
    if retry.returncode:
        return retry
    still = _unsafe_helper_source_permissions(generation, env)
    if still:
        raise InstallError(
            "helper_source_permissions_unsafe: helper sources are still group- or "
            "other-writable after one targeted uv cache clean and reinstall ("
            + ", ".join(still) + "). Another process may be writing the uv cache "
            "with a permissive umask; stop it or set UV_CACHE_DIR to a private "
            "cache, then rerun the installer."
        )
    return subprocess.CompletedProcess(
        command, 0, result.stdout + clean.stdout + retry.stdout,
        result.stderr + clean.stderr + retry.stderr,
    )
