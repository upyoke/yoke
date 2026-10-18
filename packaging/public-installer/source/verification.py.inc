class InstallerVerification:
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


    def _repair_credential_helper(self, yoke_bin: str) -> None:
        """Point registered checkouts at the active immutable helper bundle."""
        argv = [yoke_bin, "github", "credential-helper", "refresh", "--json"]
        result = self.capture_runner(argv)
        if result.returncode != 0:
            raise InstallError(_format_command_failure(argv, result))
        diagnostic = (result.stderr or result.stdout or "").strip()[-2048:]
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict) or "configured" not in payload:
            raise InstallError(
                "credential helper repair produced no result: "
                f"{diagnostic or 'no diagnostic output'}"
            )
        error = payload.get("error")
        if error:
            raise InstallError(f"credential helper repair failed: {error}")
        if payload.get("repaired"):
            print(
                self._say(
                    "Updated the git credential helper bundle for this release."
                ),
                file=self.stdout,
            )


    def _restart_running_dashboard(self, yoke_bin: str) -> None:
        argv = [yoke_bin, "ui", "restart-running", "--json"]
        try:
            result = self.capture_runner(argv)
        except OSError as exc:
            raise InstallError(
                f"ui_restart_unavailable: {exc}; rerun the installer to repair Yoke."
            ) from exc
        if result.returncode:
            raise InstallError(
                "ui_restart_failed: "
                + _format_command_failure(argv, result)
                + "; recover with `yoke ui down` and `yoke ui up --no-browser`, "
                "then rerun the installer."
            )
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            payload = None
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or type(payload.get("restarted")) is not bool
        ):
            raise InstallError(
                "ui_restart_result_invalid: dashboard restart returned no valid receipt; "
                "rerun the installer to repair the installed Yoke executable."
            )
        if payload["restarted"]:
            print(
                self._say(
                    "Restarted the running dashboard with the installed Yoke version."
                ),
                file=self.stdout,
            )


    def _record_distribution(self, yoke_bin: str) -> None:
        argv = [
            yoke_bin,
            "settings",
            "set",
            "distribution",
            json.dumps(
                {"origin": self.options.base_url, "channel": self.options.channel}
            ),
        ]
        result = self.capture_runner(argv)
        if result.returncode != 0:
            raise InstallError(
                "distribution_record_failed: " + _format_command_failure(argv, result)
            )


    def _advise_path(self) -> None:
        if self.which("yoke") is not None:
            return
        print(
            self._say("Open a new terminal to use Yoke. If it is still missing, run:"),
            file=self.stdout,
        )
        print(self._say("uv tool update-shell"), file=self.stdout)
