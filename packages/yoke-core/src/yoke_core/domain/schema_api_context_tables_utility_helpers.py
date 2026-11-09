"""Shared utility owners diagnosed by CI and installed-product validation."""

UTILITY_HELPERS_TABLES: dict[str, dict] = {
    "yoke_core.domain.watch_runner": {
        "columns": [("run_watcher", "callable")],
        "notes": (
            "Shared watcher execution lives in domain; command classifiers and "
            "entrypoints remain in tools. Wrong guess: importing watch_merge "
            "alongside watch_runner from domain in an embedded smoke command."
        ),
    },
    "yoke_core.tools.ci_runner_prepare": {
        "columns": [("start_postgres", "callable")],
        "notes": (
            "CI bootstrap imports DISPOSABLE_SERVER_SETTINGS from "
            "yoke_core.domain.test_postgres_cluster. Wrong guess: the constant "
            "remains importable from tools.pg_testcluster after its utility extraction."
        ),
    },
    "yoke_core.tools.install_yoke_launcher": {
        "columns": [("LAUNCHER_FILENAME", "constant")],
        "notes": (
            "Launcher naming is owned by yoke_core.domain.launcher_locations. "
            "Wrong guess: tools.install_yoke_launcher_core still owns "
            "LAUNCHER_FILENAME after extracting shared relay path utilities. "
            "Both launcher composition and its sweep import the shared owner."
        ),
    },
}
