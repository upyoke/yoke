def report_setup_exit(status: int, version: str, resume: str, stdout) -> int:
    if status == 0:
        return 0
    display = _display_version(version)
    installed = f"Yoke v{display} is installed" if display else "Yoke is installed"
    if status == 130:
        print(f"setup_skipped: {installed}; setup was skipped; resume with {resume}.", file=stdout)
        return 0
    print(f"setup_failed: {installed}; setup stopped, see above; resume with {resume}.", file=stdout)
    return 2


class Installer(InstallerVerification, InstallerResolution):
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
        self.terminal_runner = runner or subprocess.run
        self.which = which or shutil.which
        self.stdout = stdout or sys.stdout
        self.color = self._resolve_color(self.stdout) if color is None else color
        self.plain_glyphs = self._resolve_plain_glyphs(self.stdout)


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
    def _resolve_plain_glyphs(stream) -> bool:
        force = os.environ.get("YOKE_INSTALL_FORCE_PLAIN")
        if force == "1":
            return True
        if force == "0":
            return False
        try:
            GUTTER.encode(getattr(stream, "encoding", None) or "utf-8")
        except (UnicodeError, LookupError):
            return True
        term = os.environ.get("TERM", "")
        return (
            term.startswith("screen") or term == "dumb" or bool(os.environ.get("STY"))
        )


    @staticmethod
    def _gutter(stream) -> str:
        if Installer._resolve_plain_glyphs(stream):
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


    def run(self) -> int:
        require_native_windows_python()
        libc = (
            platform.libc_ver()[0].lower() if sys.platform.startswith("linux") else ""
        )
        if sys.platform.startswith("linux") and (
            libc == "musl" or (libc != "glibc" and glob.glob("/lib/ld-musl-*.so.1"))
        ):
            raise InstallError(
                "unsupported_libc: musl Linux (including Alpine) is unsupported. "
                "Use glibc Linux, such as Ubuntu, Debian, or Fedora, "
                "then rerun the installer."
            )
        try:
            version = self._resolve_version()
        except InstallError as exc:
            self._print_resolution_failure(exc)
            raise
        spec = product_spec(version)
        if self.options.dry_run:
            self._require_published_release(version)
            command = self.install_command(spec, config_path="<temporary uv config>")
            print(f"Resolved Yoke {version}", file=self.stdout)
            isolated = ["env", "UV_TOOL_DIR=<new private release>/tools", "UV_TOOL_BIN_DIR=<new private release>/bin", *command]
            print(f"Install command: {shlex.join(isolated)}", file=self.stdout)
            print("Publication: verify the candidate, then atomically switch the launcher; retain releases used by running commands.", file=self.stdout)
            print(
                f"Dry run: confirmed Yoke {version} is published at "
                f"{_safe_url(self.options.base_url)}. "
                "No package was installed and no configuration was written. "
                "Publication does not prove dependencies, wheel integrity, or "
                "that installation would succeed.",
                file=self.stdout,
            )
            return 0
        print(self._say("Setting up Yoke…"), file=self.stdout)
        config_path = self._write_uv_index_config()
        try:
            already = self._run_uv_install(
                self.install_command(spec, config_path=config_path)
            )
        finally:
            os.unlink(config_path)
        yoke_bin = self._resolve_installed_yoke_bin()
        shell_update = self.capture_runner([yoke_bin, "path", "fix", "--yes", "--json"])
        if shell_update.returncode:
            raise InstallError(
                "shell_path_setup_failed: "
                + (shell_update.stderr or shell_update.stdout).strip()
                + f"; run {shlex.quote(yoke_bin)} path fix --yes, then rerun the installer."
            )
        installed_version = self._smoke_yoke(yoke_bin)
        display = _display_version(installed_version)
        # Readiness comes only after every required check passes: a
        # product-boundary or credential-helper repair failure must never
        # print a "ready" screen before raising.
        self._product_boundary_audit(expected_version=version, yoke_bin=yoke_bin)
        self._repair_credential_helper(yoke_bin)
        self._record_distribution(yoke_bin)
        self._prove_hook_evaluator(yoke_bin)
        self._restart_running_dashboard(yoke_bin)
        if sys.platform != "win32":
            try:
                wsl_setup = self.terminal_runner([yoke_bin, "wsl", "setup"])
            except OSError as exc:
                raise InstallError(
                    f"wsl_systemd_setup_unavailable: {exc}. "
                    "Rerun the installer to repair the installed yoke executable."
                ) from exc
            if wsl_setup.returncode:
                raise InstallError(
                    "wsl_systemd_setup_failed: See the WSL setup reason above. "
                    "Rerun yoke wsl setup in an Ubuntu terminal with administrator access, "
                    "then rerun the installer."
                )
        if already:
            print(self._say(f"Yoke v{display} already installed"), file=self.stdout)
        else:
            print(self._say(f"Yoke v{display} is ready"), file=self.stdout)
        self._advise_path(yoke_bin)
        if sys.platform == "win32" and not self.options.no_setup:
            if self.options.yes or not sys.stdin.isatty():
                print(self._say("Run yoke setup in a new terminal."), file=self.stdout)
            else:
                try:
                    status = self.terminal_runner([yoke_bin, "setup", "--post-install"]).returncode
                except KeyboardInterrupt:
                    status = 130
                except OSError as exc:
                    print(self._say(_sanitize_diagnostic(str(exc))), file=self.stdout)
                    status = 1
                return report_setup_exit(
                    status, installed_version, "yoke setup in a new terminal", self.stdout
                )
        return 0


    def _prove_hook_evaluator(self, yoke_bin: str) -> None:
        """Prove the installed evaluator, then stop it, so no resident outlives the install.

        The release being installed owns its readiness proof. A release that
        predates ``verify`` (an update to an older version) names only
        ``restart`` and ``stop``; its own ``restart`` is its proof.
        """
        action = "verify"
        resident = self.capture_runner([yoke_bin, "hook", "resident", action])
        output = (resident.stdout or "") + "\n" + (resident.stderr or "")
        if resident.returncode and "invalid choice: 'verify'" in output:
            action = "restart"
            resident = self.capture_runner([yoke_bin, "hook", "resident", action])
            output = (resident.stdout or "") + "\n" + (resident.stderr or "")
        if resident.returncode:
            raise InstallError(
                "hook_evaluator_readiness_failed: the installed evaluator did not "
                "pass its readiness check. "
                + _bounded_diagnostic(output, DIAGNOSTIC_MAX_CHARS)
                + f"; run yoke hook resident {action}, then retry the installer."
            )
