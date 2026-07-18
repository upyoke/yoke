#!/usr/bin/env python3
"""Install the Yoke product CLI from Yoke's private package index."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.upyoke.com"
STAGE_BASE_URL = "https://api.stage.upyoke.com"
DEFAULT_CHANNEL = "stable"
GUTTER_ICON = "☀"
PLAIN_GUTTER_ICON = "*"
# Every Yoke-emitted setup line wears this amber-sun gutter so it stands out
# from any uv output that scrolls past. Colorized when the terminal supports it
# (see Installer._resolve_color).
GUTTER = GUTTER_ICON

# Truecolor SGR sequences mirroring the onboard wizard palette.
_SGR_CODES = {
    "brand": "1;38;2;63;185;80",  # bold accent #3fb950
    "bright": "38;2;86;211;100",  # accent-bright #56d364
    "dim": "38;2;125;133;144",  # dim #7d8590
    "danger": "1;38;2;248;81;73",  # bold danger #f85149
    "amber": "38;2;210;153;34",  # amber #d29922 (the sun)
}


def _paint(text: str, key: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{_SGR_CODES[key]}m{text}\033[0m"


_DEV_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+(?:\.\d+)?)\.dev\d+\+(?P<local>.+)$")
PRODUCT_PACKAGE = "yoke-cli"
LOCKSTEP_PRODUCT_PACKAGES = ("yoke-contracts", "yoke-harness", "yoke-core")
PYTHON_CONSTRAINT = ">=3.10"
PYPI_INDEX_URL = "https://pypi.org/simple/"
INDEX_STRATEGY = "first-index"
# The public installer owns resolver sources completely. Ambient uv index
# settings must not replace PyPI or insert a higher-priority index ahead of the
# Yoke index selected by the installer.
UV_INDEX_ENV_VARS = frozenset(
    {
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX",
        "UV_INDEX_STRATEGY",
        "UV_INDEX_URL",
        "UV_NO_INDEX",
    }
)
DIAGNOSTIC_MAX_CHARS = 4000
FAILURE_REASON_MAX_CHARS = 600
_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
FRESH_STATUS_ERROR_CODES = frozenset(
    {
        "config_missing",
        "schema_version",
        "connections_required",
        "active_env_required",
        "active_env",
        "temp_root_not_writable",
        "cache_dir_not_writable",
    }
)


class InstallError(RuntimeError):
    """Raised for user-actionable installer failures."""


@dataclass(frozen=True)
class InstallOptions:
    channel: str
    version: str | None
    yes: bool
    dry_run: bool
    base_url: str
    no_onboard: bool


def main(argv: Iterable[str] | None = None) -> int:
    try:
        Installer(parse_args(argv)).run()
    except InstallError as exc:
        gutter = Installer._gutter(sys.stderr)
        print(f"{gutter} {_sanitize_diagnostic(str(exc))}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: Iterable[str] | None = None) -> InstallOptions:
    parser = argparse.ArgumentParser(description="Install Yoke.")
    parser.add_argument(
        "--channel", default=os.environ.get("YOKE_CHANNEL") or DEFAULT_CHANNEL
    )
    parser.add_argument("--version", default=os.environ.get("YOKE_VERSION") or None)
    parser.add_argument(
        "--yes", action="store_true", default=_env_truthy("YOKE_INSTALL_YES")
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-onboard", action="store_true", default=_env_truthy("YOKE_NO_ONBOARD")
    )
    parser.add_argument(
        "--base-url",
        help=argparse.SUPPRESS,
        default=os.environ.get("YOKE_INSTALL_BASE_URL") or DEFAULT_BASE_URL,
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return InstallOptions(
        channel=args.channel,
        version=args.version,
        yes=bool(args.yes),
        dry_run=bool(args.dry_run),
        base_url=args.base_url.rstrip("/"),
        no_onboard=bool(args.no_onboard),
    )


class Installer:
    def __init__(
        self,
        options: InstallOptions,
        *,
        fetcher=None,
        runner=None,
        which=None,
        stdout=None,
        color=None,
    ) -> None:
        self.options = options
        self.fetcher = fetcher or fetch_url
        self.capture_runner = runner or run_command_capture
        self.which = which or shutil.which
        self.stdout = stdout or sys.stdout
        self.color = self._resolve_color(self.stdout) if color is None else color
        self.plain_glyphs = self._resolve_plain_glyphs()

    @staticmethod
    def _resolve_color(stream) -> bool:
        # The shim hands down its own color decision via YOKE_INSTALL_FORCE_COLOR
        # so the setup log matches the welcome banner exactly; absent that we fall
        # back to the usual NO_COLOR / tty / TERM gating.
        force = os.environ.get("YOKE_INSTALL_FORCE_COLOR")
        if force == "1":
            return True
        if force == "0":
            return False
        if os.environ.get("NO_COLOR") is not None:
            return False
        isatty = getattr(stream, "isatty", None)
        if not callable(isatty) or not isatty():
            return False
        term = os.environ.get("TERM", "")
        return bool(term) and term != "dumb"

    @staticmethod
    def _resolve_plain_glyphs() -> bool:
        force = os.environ.get("YOKE_INSTALL_FORCE_PLAIN")
        if force == "1":
            return True
        if force == "0":
            return False
        term = os.environ.get("TERM", "")
        return (
            term.startswith("screen") or term == "dumb" or bool(os.environ.get("STY"))
        )

    @staticmethod
    def _gutter(stream) -> str:
        if Installer._resolve_plain_glyphs():
            return PLAIN_GUTTER_ICON
        return _paint(GUTTER, "amber", enabled=Installer._resolve_color(stream))

    def _say(self, message: str) -> str:
        """One branded gutter line, plain in screen/dumb terminals."""
        if self.plain_glyphs:
            return f"{PLAIN_GUTTER_ICON} {message}"
        return f"{_paint(GUTTER, 'amber', enabled=self.color)} {message}"

    @property
    def index_url(self) -> str:
        return f"{self.options.base_url}/simple/"

    def run(self) -> None:
        try:
            version = self._resolve_version()
        except InstallError as exc:
            self._print_resolution_failure(exc)
            raise
        spec = product_spec(version)
        if self.options.dry_run:
            command = self.install_command(spec, config_path="<temporary uv config>")
            print(
                f"Resolved Yoke {version}"
                if version
                else f"Installing latest Yoke from {_safe_url(self.index_url)}",
                file=self.stdout,
            )
            print(f"Install command: {shlex.join(command)}", file=self.stdout)
            print(
                "Dry run: resolved the install plan; no changes were made.",
                file=self.stdout,
            )
            return
        print(self._say("Setting up Yoke…"), file=self.stdout)
        config_path = self._write_uv_index_config()
        try:
            already = self._run_uv_install(
                self.install_command(spec, config_path=config_path)
            )
        finally:
            os.unlink(config_path)
        yoke_bin = self._resolve_installed_yoke_bin()
        installed_version = self._smoke_yoke(yoke_bin)
        display = _display_version(installed_version)
        if already:
            print(self._say(f"Yoke v{display} already installed"), file=self.stdout)
        else:
            print(self._say(f"Yoke v{display} is ready"), file=self.stdout)
        self._product_boundary_audit(expected_version=version, yoke_bin=yoke_bin)
        self._advise_path()

    def install_command(
        self, spec: str, *, config_path: str | None = None
    ) -> list[str]:
        command = [
            "uv",
            "tool",
            "install",
            spec,
            "--python",
            PYTHON_CONSTRAINT,
            "--reinstall",
            "--force",
            *_with_product_requirements(_product_spec_version(spec)),
            "--default-index",
            PYPI_INDEX_URL,
            "--index-strategy",
            INDEX_STRATEGY,
        ]
        if config_path is not None:
            command.extend(["--config-file", config_path])
        return command

    def _write_uv_index_config(self) -> str:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="yoke-uv-index-",
            suffix=".toml",
            delete=False,
        ) as file:
            file.write(self._uv_index_config_text())
            return file.name

    def _uv_index_config_text(self) -> str:
        return (
            "[[index]]\n"
            'name = "yoke-private"\n'
            f'url = "{self.index_url}"\n'
            "ignore-error-codes = [403]\n"
        )

    def _resolve_version(self) -> str | None:
        if self.options.version:
            return self.options.version
        channel_url = (
            f"{self.options.base_url}/dist/channels/{self.options.channel}.json"
        )
        try:
            channel_bytes = self.fetcher(channel_url)
        except InstallError as exc:
            if (
                self.options.channel == "latest"
                and self.options.base_url == DEFAULT_BASE_URL
            ):
                raise InstallError(
                    f"{exc}. The latest channel is published from "
                    f"{STAGE_BASE_URL}; use that installer origin for "
                    "pre-stable releases"
                ) from exc
            raise
        channel = _loads_json(channel_bytes, f"{self.options.channel} channel")
        version = channel.get("version")
        if not isinstance(version, str) or not version:
            raise InstallError(
                f"{self.options.channel} channel is missing a version pin"
            )
        return version

    def _run_uv_install(self, command: Sequence[str]) -> bool:
        result = self.capture_runner(list(command))
        if result.returncode != 0:
            print(self._say("Install failed"), file=self.stdout)
            print(
                _paint("✗ Couldn't install Yoke.", "danger", enabled=self.color),
                file=self.stdout,
            )
            reason = _paint(_failure_reason(result), "dim", enabled=self.color)
            print(f"  {reason}", file=self.stdout)
            print("Try again:", file=self.stdout)
            retry = _paint(
                _rerun_command(self.options.base_url), "bright", enabled=self.color
            )
            print(f"  {retry}", file=self.stdout, flush=True)
            raise InstallError(_format_command_failure(command, result))
        return _uv_reported_already_installed(result)

    def _print_resolution_failure(self, exc: InstallError) -> None:
        print(self._say("Install failed"), file=self.stdout)
        print(
            _paint(
                "✗ Couldn't find a Yoke release to install.",
                "danger",
                enabled=self.color,
            ),
            file=self.stdout,
        )
        print(
            f"  {_paint(_sanitize_diagnostic(str(exc)), 'dim', enabled=self.color)}",
            file=self.stdout,
        )
        print("Try again:", file=self.stdout)
        retry_base_url = self.options.base_url
        if (
            self.options.channel == "latest"
            and self.options.base_url == DEFAULT_BASE_URL
        ):
            retry_base_url = STAGE_BASE_URL
        retry = _paint(
            _rerun_command(retry_base_url), "bright", enabled=self.color
        )
        print(f"  {retry}", file=self.stdout, flush=True)

    def _resolve_installed_yoke_bin(self) -> str:
        seen: set[str] = set()
        for candidate in self._installed_yoke_candidates():
            if candidate in seen:
                continue
            seen.add(candidate)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        found = self.which("yoke")
        if found:
            return found
        raise InstallError("yoke command not found after install")

    def _installed_yoke_candidates(self) -> Iterable[str]:
        uv_tool_bin = os.environ.get("UV_TOOL_BIN_DIR")
        if uv_tool_bin:
            yield os.path.join(uv_tool_bin, "yoke")
        xdg_bin = os.environ.get("XDG_BIN_HOME")
        if xdg_bin:
            yield os.path.join(xdg_bin, "yoke")
        uv_bin = self.capture_runner(["uv", "tool", "dir", "--bin"])
        if uv_bin.returncode == 0:
            directory = uv_bin.stdout.strip()
            if directory and "\n" not in directory and os.path.isabs(directory):
                yield os.path.join(directory, "yoke")
        home = os.path.expanduser("~")
        if home and home != "~":
            yield os.path.join(home, ".local", "bin", "yoke")

    def _smoke_yoke(self, yoke_bin: str = "yoke") -> str:
        version = ""
        for argv in (
            [yoke_bin, "--version"],
            [yoke_bin, "--help"],
        ):
            result = self.capture_runner(argv)
            if result.returncode != 0:
                raise InstallError(_format_command_failure(argv, result))
            if argv[1:] == ["--version"]:
                version = result.stdout.strip()
        return version

    def _product_boundary_audit(
        self,
        *,
        expected_version: str | None = None,
        yoke_bin: str = "yoke",
    ) -> None:
        source_dev_authority = "source-dev/admin"
        argv = [yoke_bin, "status", "--json"]
        result = self.capture_runner(argv)
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InstallError(
                "product-boundary audit failed: `yoke status --json` did not "
                f"return valid JSON ({exc})."
            ) from exc
        if result.returncode != 0:
            unexpected = _unexpected_status_error_codes(status)
            if unexpected:
                raise InstallError(
                    "product-boundary audit failed: `yoke status --json` "
                    "reported unexpected errors on a fresh install: "
                    + ", ".join(unexpected)
                )
        connection = status.get("connection") if isinstance(status, dict) else None
        authority = ""
        if isinstance(connection, dict):
            authority = str(connection.get("client_authority") or "")
        if authority == source_dev_authority:
            raise InstallError(
                "product-boundary audit failed: yoke reports client authority "
                f"{authority!r}; a product install must use the product API, not "
                "source-dev/admin authority."
            )
        # The engine (yoke-core) is installed on every machine by design; the
        # audit verifies it stays inert — the client must hold product-API
        # authority, never local source-dev/admin authority. Reject a reported
        # authority violation before diagnosing package completeness so the
        # security boundary remains the primary failure.
        runtime = status.get("runtime") if isinstance(status, dict) else None
        _verify_product_package_presence(runtime)
        if expected_version:
            _verify_product_package_versions(runtime, expected_version)

    def _advise_path(self) -> None:
        if self.which("yoke") is not None:
            return
        print(
            self._say("Yoke isn't on your PATH yet — to add it, run:"), file=self.stdout
        )
        print(self._say("~/.local/bin/yoke path fix"), file=self.stdout)


def product_spec(version: str | None) -> str:
    if version:
        return f"{PRODUCT_PACKAGE}=={version}"
    return PRODUCT_PACKAGE


def _rerun_command(base_url: str) -> str:
    return f"curl -fsSL {_safe_url(base_url).rstrip('/')}/install | bash"


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


def run_command_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in UV_INDEX_ENV_VARS
    }
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


def _format_command_failure(
    command: Sequence[str],
    result: subprocess.CompletedProcess[str],
) -> str:
    safe_command = _bounded_diagnostic(" ".join(command), DIAGNOSTIC_MAX_CHARS)
    safe_stdout = _bounded_diagnostic(result.stdout or "", DIAGNOSTIC_MAX_CHARS)
    safe_stderr = _bounded_diagnostic(result.stderr or "", DIAGNOSTIC_MAX_CHARS)
    return (
        "Yoke dependency resolution uses the configured Yoke package index "
        f"and public PyPI ({PYPI_INDEX_URL}).\n"
        f"command failed with {result.returncode}: {safe_command}\n"
        f"stdout:\n{safe_stdout}\n"
        f"stderr:\n{safe_stderr}"
    )


def _bounded_diagnostic(value: str, limit: int) -> str:
    safe = _sanitize_diagnostic(value)
    if len(safe) <= limit:
        return safe
    return f"<earlier output omitted>\n{safe[-limit:]}"


def _sanitize_diagnostic(value: str) -> str:
    """Remove URL credentials/query material from operator-visible text."""

    return _URL_RE.sub(lambda match: _safe_url(match.group(0)), value)


def _safe_url(value: str) -> str:
    raw = str(value or "")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return "<redacted-url>"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return raw
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, "", "")
    )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "y"}


if __name__ == "__main__":
    raise SystemExit(main())
