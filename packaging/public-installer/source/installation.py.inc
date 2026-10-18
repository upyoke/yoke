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
            print(f"Install command: {shlex.join(command)}", file=self.stdout)
            print(
                f"Dry run: confirmed Yoke {version} is published at "
                f"{_safe_url(self.options.base_url)}. "
                "No package was installed and no configuration was written. "
                "Publication does not prove dependencies, wheel integrity, or "
                "that installation would succeed.",
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
        shell_update = self.capture_runner(["uv", "tool", "update-shell"])
        shell_unknown = bool(shell_update.returncode) and (
            "current shell could not be determined" in shell_update.stderr
        )
        if shell_update.returncode and not shell_unknown:
            raise InstallError(
                "uv_shell_update_failed: "
                + shell_update.stderr.strip()
                + "; run `uv tool update-shell`, then rerun the installer."
            )
        yoke_bin = self._resolve_installed_yoke_bin()
        installed_version = self._smoke_yoke(yoke_bin)
        display = _display_version(installed_version)
        # Readiness comes only after every required check passes: a
        # product-boundary or credential-helper repair failure must never
        # print a "ready" screen before raising.
        self._product_boundary_audit(expected_version=version, yoke_bin=yoke_bin)
        self._repair_credential_helper(yoke_bin)
        self._record_distribution(yoke_bin)
        argv = [yoke_bin, "hook", "resident", "restart"]
        resident = self.capture_runner(argv)
        if resident.returncode:
            raise InstallError(
                "hook_evaluator_readiness_failed: the installed evaluator did not "
                "pass its readiness check. "
                + _bounded_diagnostic(
                    (resident.stdout or "") + "\n" + (resident.stderr or ""),
                    DIAGNOSTIC_MAX_CHARS,
                )
                + "; run yoke hook resident restart, then retry the installer."
            )
        self._restart_running_dashboard(yoke_bin)
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
        if shell_unknown:
            bin_dir = shlex.quote(os.path.dirname(yoke_bin))
            print(
                self._say(f'Add Yoke to PATH: export PATH={bin_dir}:"$PATH"'),
                file=self.stdout,
            )
        else:
            self._advise_path()
