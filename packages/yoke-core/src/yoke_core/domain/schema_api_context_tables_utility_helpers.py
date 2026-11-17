"""Shared utility owners diagnosed by CI and installed-product validation."""

UTILITY_HELPERS_TABLES: dict[str, dict] = {
    "yoke_contracts.owner_private_path": {
        "columns": [("is_others_unwritable_directory", "callable"),
                    ("is_current_user_owned_path", "callable")],
        "notes": (
            "Dockerfile's PostgreSQL bootstrap imports this module from explicit "
            "source bind mounts before wheels exist. Wrong guess: mounting the "
            "previous owner-private dependencies also covers a new transitive "
            "import. Include windows_others_unwritable_directory.py alongside "
            "windows_private_directory.py or bootstrap raises cannot import name. "
            "Verify with test_container_bootstrap_imports.py's declared-mount check."
        ),
    },
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
            "yoke_core.domain.pytest_cluster_identity. Wrong guess: the constant "
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
