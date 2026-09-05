"""Guaranteed-macOS-primitive program for the dedicated Test Mac reset."""

from __future__ import annotations

from pathlib import PurePosixPath
import shlex

from yoke_cli.config.path_doctor import resolve_path_state_contract

from yoke_harness._ssh_mac_full_reset_reap_body import REAP_FUNCTIONS
from yoke_harness._ssh_mac_full_reset_relay_body import RELAY_SERVICE_FUNCTIONS
from yoke_harness._ssh_mac_full_reset_script_body import SCRIPT_BODY
from yoke_harness._ssh_mac_full_reset_self_host_body import SELF_HOST_FUNCTIONS
from yoke_harness.ssh_mac_full_reset_contract import (
    COMPOSE_PROJECT_LABEL,
    CONTAINER_RUNTIME_PATHS,
    CONTAINER_RUNTIME_PROCESS_ANCHOR,
    CONTAINER_RUNTIME_STOP_TIMEOUT_SECONDS,
    FULL_DISK_ACCESS_PROBE_PATH,
    FULL_RESET_MARKER,
    FullResetPathContract,
    GOLDEN_MANIFEST_SUFFIX,
    LAUNCHCTL_PATH,
    PRESERVED_HOME_ENTRIES,
    RELAY_SERVICE_DOMAIN,
    RELAY_SERVICE_LABEL,
    RELAY_SERVICE_LABEL_PREFIX,
    RELAY_UNLOAD_TIMEOUT_SECONDS,
    RESET_ABSENT_KIND_LEFTOVER,
    RESET_ABSENT_KIND_LIVE_PROCESS,
    RESET_ABSENT_PATH_PREFIX,
    RESET_FAILURE_PREFIX,
    RESET_LOAD_AVERAGE_PREFIX,
    RESET_PHASES,
    RESET_PROCESS_REAPED_PREFIX,
    RESET_REAP_MARKER_ANCHOR,
    RESET_REAP_MARKER_SUFFIX,
    RESET_REAP_ONBOARD_ANCHOR,
    RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED,
    RESET_RELAY_SERVICE_PREFIX,
    RESET_RELAY_UNLOADED_PREFIX,
    RESET_RESTORED_ENTRIES_PREFIX,
    RESET_RESTORE_UNRESTORED_PREFIX,
    RESET_SELF_HOST_CONTAINERS_PREFIX,
    RESET_SELF_HOST_IMAGES_PREFIX,
    RESET_SELF_HOST_VOLUMES_PREFIX,
    RESTORE_REPORT_ENTRY_CAP,
    SELF_HOST_COMPOSE_PROJECT,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_TEMP_FILES,
    YOKE_STATE_DIR_NAME,
    resolve_full_reset_path_contract,
)


TYPE_RECONCILIATION_FUNCTIONS = r"""
reconcile_entry_types() {
  local source="$1" destination="$2" remaining=""
  if [[ -d "$destination" && ! -L "$destination" ]]; then
    /bin/chmod -RN "$destination" 2>/dev/null || true
    /usr/bin/find "$destination" -type d \
      -exec /bin/chmod u+rwx {} \; || return 1
  fi
  if lexists "$destination"; then
    /bin/rm -rf -- "$destination" 2>/dev/null || true
  fi
  if ! lexists "$destination"; then
    return 0
  fi
  if [[ -d "$source" && ! -L "$source" \
      && -d "$destination" && ! -L "$destination" ]]; then
    remaining=$(
      /usr/bin/find "$destination" -mindepth 1 -print | /usr/bin/wc -l
    )
    remaining="${remaining// /}"
    [[ "$remaining" == 0 ]] && return 0
  fi
  print -u2 -- "restore destination remains occupied: $destination"
  return 1
}

restore_entry() {
  local captured="$1" target_dir="$2"
  local destination="${target_dir%/}/${captured:t}"
  reconcile_entry_types "$captured" "$destination" || return 1
  /bin/cp -Rpf "$captured" "$target_dir"
}

# The aggregate error log decides the outcome; this names WHICH captured entry
# produced each report, because the aggregate is a wall of copier diagnostics
# and the entry that stopped the restore is the fact an operator needs.
restore_captured_entry() {
  local captured="$1" target_dir="$2" entry_log="$restore_error_log.entry"
  : > "$entry_log"
  restore_entry "$captured" "$target_dir" 2>"$entry_log" || true
  if [[ -s "$entry_log" ]]; then
    print -r -- "${captured:t}" >> "$restore_failure_report"
    /bin/cat -- "$entry_log" >> "$restore_error_log"
  fi
  /bin/rm -f -- "$entry_log" 2>/dev/null || true
  return 0
}
"""


def _array(values: tuple[str, ...]) -> str:
    return "(" + shlex.join(values) + ")"


def preserved_levels(
    preserved: tuple[str, ...] = PRESERVED_HOME_ENTRIES,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Map each directory a preserved entry passes through to its kept children.

    The clear and the restore both walk this structure, which is what makes them
    symmetric: each descends exactly as far as a preserved path's ancestor chain
    requires and no further. Flattening either into one recursive call is the
    defect the symmetry exists to prevent, because the captured copy of a
    preserved path would then overwrite the live one.
    """
    kept: dict[str, set[str]] = {}
    for entry in preserved:
        parts = PurePosixPath(entry).parts
        if not parts or ".." in parts or entry.startswith("/"):
            raise ValueError("preserved home entry must be a relative path")
        for depth in range(len(parts)):
            kept.setdefault("/".join(parts[:depth]), set()).add(parts[depth])
    return tuple(
        (directory, tuple(sorted(names)))
        for directory, names in sorted(
            kept.items(),
            key=lambda item: (len(PurePosixPath(item[0]).parts), item[0]),
        )
    )


def _level_paths(directory: str) -> tuple[str, str, str]:
    """Return one level's home source, golden source, and restore target."""
    if not directory:
        return '"$home"', '"$golden"', '"$home/"'
    quoted = shlex.quote(directory)
    return f'"$home"/{quoted}', f'"$golden"/{quoted}', f'"$home"/{quoted}/'


def _kept_predicate(names: tuple[str, ...]) -> str:
    return " ".join(f"-not -name {shlex.quote(name)}" for name in names)


def render_level_functions(
    levels: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    """Render the paired clear and restore walks over one preserved structure."""
    clear_lines = ["clear_home_levels() {"]
    restore_lines = ["restore_golden_levels() {"]
    for directory, names in levels:
        home_level, golden_level, target = _level_paths(directory)
        keep = _kept_predicate(names)
        clear_lines.append(
            f"  /usr/bin/find {home_level} -mindepth 1 -maxdepth 1 {keep} "
            "-exec /bin/rm -rf -- {} + 2>/dev/null || true"
        )
        restore_lines.extend(
            (
                "  while IFS= read -r -d '' captured; do",
                f'    restore_captured_entry "$captured" {target}',
                "  done < <(",
                f"    /usr/bin/find {golden_level} -mindepth 1 -maxdepth 1 "
                f"{keep} -print0",
                "  )",
            )
        )
    clear_lines.extend(("  return 0", "}"))
    restore_lines.extend(("  return 0", "}"))
    return "\n".join((*clear_lines, "", *restore_lines))


def render_full_reset_script(contract: FullResetPathContract) -> str:
    """Render the reset program from one validated product PATH contract."""
    return "\n".join(
        (
            "#!/bin/zsh",
            "set -eu",
            "setopt PIPE_FAIL",
            "umask 077",
            f"full_reset_marker={shlex.quote(FULL_RESET_MARKER)}",
            f"full_disk_access_probe={shlex.quote(FULL_DISK_ACCESS_PROBE_PATH)}",
            f"manifest_suffix={shlex.quote(GOLDEN_MANIFEST_SUFFIX)}",
            f"shell_path={shlex.quote(contract.shell_path)}",
            "clean_shell_path=/usr/bin:/bin:/usr/sbin:/sbin",
            f"tool_bin_suffix={shlex.quote(contract.tool_bin_suffix)}",
            f"reset_failure_prefix={shlex.quote(RESET_FAILURE_PREFIX)}",
            f"reap_marker_anchor={shlex.quote(RESET_REAP_MARKER_ANCHOR)}",
            f"reap_marker_suffix={shlex.quote(RESET_REAP_MARKER_SUFFIX)}",
            f"reap_onboard_anchor={shlex.quote(RESET_REAP_ONBOARD_ANCHOR)}",
            f"reset_process_reaped_prefix={shlex.quote(RESET_PROCESS_REAPED_PREFIX)}",
            f"reset_load_average_prefix={shlex.quote(RESET_LOAD_AVERAGE_PREFIX)}",
            f"restored_entries_prefix={shlex.quote(RESET_RESTORED_ENTRIES_PREFIX)}",
            "restore_unrestored_prefix=" + shlex.quote(RESET_RESTORE_UNRESTORED_PREFIX),
            f"restore_report_entry_cap={RESTORE_REPORT_ENTRY_CAP}",
            f"yoke_state_suffix={shlex.quote(YOKE_STATE_DIR_NAME)}",
            "self_host_containers_prefix="
            + shlex.quote(RESET_SELF_HOST_CONTAINERS_PREFIX),
            "self_host_volumes_prefix=" + shlex.quote(RESET_SELF_HOST_VOLUMES_PREFIX),
            "self_host_images_prefix=" + shlex.quote(RESET_SELF_HOST_IMAGES_PREFIX),
            f"compose_project_label={shlex.quote(COMPOSE_PROJECT_LABEL)}",
            "self_host_compose_project=" + shlex.quote(SELF_HOST_COMPOSE_PROJECT),
            "container_runtime_anchor=" + shlex.quote(CONTAINER_RUNTIME_PROCESS_ANCHOR),
            "container_runtime_stop_timeout="
            + str(CONTAINER_RUNTIME_STOP_TIMEOUT_SECONDS),
            f"container_runtime_paths={_array(CONTAINER_RUNTIME_PATHS)}",
            f"launchctl_path={shlex.quote(LAUNCHCTL_PATH)}",
            f"relay_label={shlex.quote(RELAY_SERVICE_LABEL)}",
            f"relay_label_prefix={shlex.quote(RELAY_SERVICE_LABEL_PREFIX)}",
            f"relay_domain={shlex.quote(RELAY_SERVICE_DOMAIN)}",
            f"relay_unload_timeout={RELAY_UNLOAD_TIMEOUT_SECONDS}",
            f"relay_unloaded_prefix={shlex.quote(RESET_RELAY_UNLOADED_PREFIX)}",
            "relay_service_prefix=" + shlex.quote(RESET_RELAY_SERVICE_PREFIX),
            "relay_service_kind_unload_failed="
            + shlex.quote(RESET_RELAY_SERVICE_KIND_UNLOAD_FAILED),
            *(
                f"reset_phase_{name}={shlex.quote(value)}"
                for name, value in RESET_PHASES.items()
            ),
            f"tools={_array(contract.tools)}",
            f"preserved_entries={_array(PRESERVED_HOME_ENTRIES)}",
            f"yoke_absent_directories={_array(YOKE_ABSENT_RELATIVE_DIRECTORIES)}",
            f"yoke_absent_files={_array(contract.tool_file_suffixes)}",
            f"yoke_absent_temp_files={_array(YOKE_ABSENT_TEMP_FILES)}",
            f"reset_absent_prefix={shlex.quote(RESET_ABSENT_PATH_PREFIX)}",
            "reset_absent_kind_leftover=" + shlex.quote(RESET_ABSENT_KIND_LEFTOVER),
            "reset_absent_kind_live_process="
            + shlex.quote(RESET_ABSENT_KIND_LIVE_PROCESS),
            REAP_FUNCTIONS.lstrip(),
            RELAY_SERVICE_FUNCTIONS.lstrip(),
            SELF_HOST_FUNCTIONS.lstrip(),
            TYPE_RECONCILIATION_FUNCTIONS.lstrip(),
            render_level_functions(preserved_levels()),
            SCRIPT_BODY.lstrip(),
        )
    )


_REFERENCE_PATH_STATE = resolve_path_state_contract(
    env={"HOME": "/", "SHELL": "/bin/zsh"}
)
FULL_RESET_SCRIPT = render_full_reset_script(
    resolve_full_reset_path_contract(_REFERENCE_PATH_STATE)
)


__all__ = [
    "FULL_RESET_SCRIPT",
    "preserved_levels",
    "render_full_reset_script",
    "render_level_functions",
]
