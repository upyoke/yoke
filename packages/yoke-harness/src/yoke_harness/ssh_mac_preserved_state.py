"""Exact macOS state kept live rather than captured and restored."""

from __future__ import annotations

import json
import shlex


# SSH carries the restore; the live TCC grant cannot be recreated by copying.
# The OS-managed secure audiovisual preference is root-owned inside the user
# container. Keep it live instead of changing its owner or snapshotting it.
OS_MANAGED_HOME_ENTRIES = (
    "Library/Group Containers/group.com.apple.secure-control-center-preferences/"
    "Library/Preferences/group.com.apple.secure-control-center-preferences.av.plist",
)
PRESERVED_HOME_ENTRIES = (
    ".ssh",
    "Library/Application Support/com.apple.TCC",
    *OS_MANAGED_HOME_ENTRIES,
)
OS_MANAGED_FILE_OWNER = (0, 0)
OS_MANAGED_MANIFEST_KEY = "os_managed_preserved_entries"
OS_MANAGED_INVALID_PREFIX = "YOKE_OS_MANAGED_STATE_INVALID "
OS_MANAGED_MANIFEST_VALUE = json.dumps(
    [
        {
            "path": path,
            "uid": OS_MANAGED_FILE_OWNER[0],
            "gid": OS_MANAGED_FILE_OWNER[1],
            "type": "regular",
        }
        for path in OS_MANAGED_HOME_ENTRIES
    ],
    separators=(",", ":"),
)


def render_preserved_state_contract() -> str:
    """Render shared validation, exact capture exclusions and manifest identity."""
    ownership = " ".join(
        '! -path "$home"/' + shlex.quote(path) for path in OS_MANAGED_HOME_ENTRIES
    )
    capture = " ".join(
        "! -path " + shlex.quote("./" + path) for path in OS_MANAGED_HOME_ENTRIES
    )
    return "\n".join(
        (
            "os_managed_entries=(" + shlex.join(OS_MANAGED_HOME_ENTRIES) + ")",
            "os_managed_owner="
            + shlex.quote(":".join(map(str, OS_MANAGED_FILE_OWNER))),
            "os_managed_manifest_line="
            + shlex.quote(OS_MANAGED_MANIFEST_KEY + " " + OS_MANAGED_MANIFEST_VALUE),
            "os_managed_manifest_key=" + shlex.quote(OS_MANAGED_MANIFEST_KEY),
            _VALIDATION_FUNCTIONS.strip(),
            "list_foreign_home_entries() {",
            f'  /usr/bin/find "$home" -xdev ! -user "$capture_user" {ownership} -print',
            "}",
            "list_capture_entries() {",
            f"  /usr/bin/find . -mindepth 1 ! -type s ! -type p {capture} -print0",
            "}",
        )
    )


_VALIDATION_FUNCTIONS = r"""
is_os_managed_entry() {
  local suffix
  for suffix in "${os_managed_entries[@]}"; do
    [[ "$1" == "$suffix" ]] && return 0
  done
  return 1
}

assert_os_managed_preserved_state() {
  local suffix target parent owner
  for suffix in "${os_managed_entries[@]}"; do
    target="$home/$suffix"
    parent="${target:h}"
    while [[ "$parent" != "$home" ]]; do
      if [[ -L "$parent" || ( -e "$parent" && ! -d "$parent" ) ]]; then
        failure_detail="$os_managed_invalid_prefix$parent"
        return 1
      fi
      parent="${parent:h}"
    done
    lexists "$target" || continue
    if [[ ! -f "$target" || -L "$target" ]]; then
      failure_detail="$os_managed_invalid_prefix$target"
      return 1
    fi
    owner=$(/usr/bin/stat -f '%u:%g' "$target" 2>/dev/null) || {
      failure_detail="$os_managed_invalid_prefix$target"
      return 1
    }
    if [[ "$owner" != "$os_managed_owner" ]]; then
      failure_detail="$os_managed_invalid_prefix$target"
      return 1
    fi
  done
  return 0
}

validate_preserved_manifest() {
  # Older sealed baselines predate the declaration. Preserve the live entry
  # for them too; a present declaration must match the current closed contract.
  if /usr/bin/grep -q "^$os_managed_manifest_key " "$golden$manifest_suffix"; then
    /usr/bin/grep -Fxq -- "$os_managed_manifest_line" "$golden$manifest_suffix" || return 1
    local suffix
    for suffix in "${os_managed_entries[@]}"; do
      lexists "$golden/$suffix" && return 1
    done
  fi
  return 0
}
"""
