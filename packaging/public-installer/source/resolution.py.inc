class InstallerResolution:
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
                self.options.channel != DEFAULT_CHANNEL
                and self.options.base_url == DEFAULT_BASE_URL
            ):
                raise InstallError(
                    f"{exc}. This installer origin publishes the "
                    f"{DEFAULT_CHANNEL} channel, not {self.options.channel}"
                ) from exc
            raise
        channel = _loads_json(channel_bytes, f"{self.options.channel} channel")
        version = channel.get("version")
        if not isinstance(version, str) or not version:
            raise InstallError(
                f"{self.options.channel} channel is missing a version pin"
            )
        _require_channel_release_evidence(channel, self.options.channel)
        return version


    def _require_published_release(self, version: str | None) -> None:
        """Refuse a dry-run whose exact version is not published at this origin."""
        origin = _safe_url(self.options.base_url)
        if not version:
            raise InstallError(
                "installer_release_unpublished: dry-run resolved no Yoke version "
                f"at {origin}; pass --version or a channel that names a published "
                "release, then rerun the installer"
            )
        url = _release_records_url(self.options.base_url, version)
        try:
            payload_bytes = self.fetcher(url)
        except InstallError as exc:
            raise _publication_fetch_error(version, origin, exc) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise _publication_fetch_error(version, origin, exc) from None
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _publication_error(
                kind="unverified",
                version=version,
                origin=origin,
                detail=f"release record is not valid JSON ({exc})",
            ) from None
        if not isinstance(payload, list):
            raise _publication_error(
                kind="unverified",
                version=version,
                origin=origin,
                detail="release record is not a JSON list",
            )
        if not payload:
            raise _publication_error(
                kind="unpublished",
                version=version,
                origin=origin,
                detail="release record lists no published wheels",
            )


    def _run_uv_install(self, command: Sequence[str]) -> bool:
        result = self.capture_runner(list(command))
        if result.returncode != 0:
            probe = self.capture_runner(
                ["uv", "python", "find", "--no-python-downloads", PYTHON_CONSTRAINT]
            )
            if probe.returncode != 0:
                raise InstallError(
                    f"supported_python_unavailable: Yoke supports Python {PYTHON_CONSTRAINT}. "
                    "Automatic managed-Python download failed or is disabled. "
                    "Check network access and uv's Python download settings, or run "
                    f"uv python install {shlex.quote(PYTHON_CONSTRAINT)}, then rerun "
                    "the installer or yoke update. " + _failure_reason(result)
                )
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
        retry_channel = (
            DEFAULT_CHANNEL
            if self.options.base_url == DEFAULT_BASE_URL
            and self.options.channel != DEFAULT_CHANNEL
            else None
        )
        retry = _paint(
            _rerun_command(self.options.base_url, channel=retry_channel),
            "bright",
            enabled=self.color,
        )
        print(f"  {retry}", file=self.stdout, flush=True)
