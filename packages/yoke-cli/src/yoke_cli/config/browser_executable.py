"""One machine setting for a proven system Chromium executable."""

from pathlib import Path

from yoke_cli.config import machine_config, machine_config_mutation as mutation

SETTING_KEY = "browser_executable_path"
# A process projection of SETTING_KEY, never a second persisted setting.
EXECUTABLE_ENV = "YOKE_BROWSER_EXECUTABLE_PATH"


def configured(*, path=None) -> str | None:
    settings = machine_config.load_config(path).get("settings", {})
    if not isinstance(settings, dict):
        raise RuntimeError(
            "browser_settings_invalid: repair machine settings to an object"
        )
    value = settings.get(SETTING_KEY)
    if value is None:
        return None
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RuntimeError(
            f"browser_executable_invalid: settings.{SETTING_KEY} must be an absolute "
            "Chromium path; repair it, then retry yoke qa browser setup"
        )
    return value


@mutation.serialized_mutation
def save(value: str | None, *, path=None) -> None:
    if value is not None and not Path(value).is_absolute():
        raise ValueError("browser_executable_invalid: use an absolute Chromium path")
    payload, cfg_path = mutation.load_payload(path)
    settings = payload.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise RuntimeError(
            "browser_settings_invalid: repair machine settings to an object"
        )
    if value is None:
        settings.pop(SETTING_KEY, None)
    else:
        settings[SETTING_KEY] = value
    mutation.write_payload(payload, cfg_path, allow_unconfigured=True)


def project_environment(env: dict[str, str], executable: str | None) -> None:
    env.pop(EXECUTABLE_ENV, None)
    if executable:
        env[EXECUTABLE_ENV] = executable
