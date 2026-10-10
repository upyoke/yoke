"""Exact macOS state kept live rather than captured and restored."""

from __future__ import annotations

import json
import shlex

from yoke_contracts.browser_identity import LIVE_IDENTITY_STORE_HOME_ENTRY


# SSH carries the restore; the live TCC grant cannot be recreated by copying.
# The OS-managed secure audiovisual preference is root-owned inside the user
# container. Keep it live instead of changing its owner or snapshotting it.
OS_MANAGED_HOME_ENTRIES = (
    "Library/Group Containers/group.com.apple.secure-control-center-preferences/"
    "Library/Preferences/group.com.apple.secure-control-center-preferences.av.plist",
)
REQUIRED_PRESERVED_HOME_ENTRIES = (
    ".ssh",
    "Library/Application Support/com.apple.TCC",
)
# The live harness logins. Claude and Cursor keep theirs in the login Keychain
# (Claude falls back to its credentials file); Codex keeps its in auth.json, or
# in the Keychain when configured for it. A restored copy of any of them is the
# golden's rotated token, so they stay live and are kept only when present.
HARNESS_LOGIN_HOME_ENTRIES = (
    "Library/Keychains",
    ".claude/.credentials.json",
    ".codex/auth.json",
)
# The live browser identity profiles. Sites rotate session cookies, so a
# restored copy is the golden's stale sign-in for the same reason a restored
# harness login is; the store stays live and is kept only when present.
LIVE_IDENTITY_HOME_ENTRIES = (LIVE_IDENTITY_STORE_HOME_ENTRY,)
PRESERVED_HOME_ENTRIES = (
    *REQUIRED_PRESERVED_HOME_ENTRIES,
    *HARNESS_LOGIN_HOME_ENTRIES,
    *OS_MANAGED_HOME_ENTRIES,
    *LIVE_IDENTITY_HOME_ENTRIES,
)
PRESERVED_MANIFEST_KEY = "preserved_home_entries"
PRESERVED_MANIFEST_VALUE = json.dumps(
    list(PRESERVED_HOME_ENTRIES), separators=(",", ":")
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
    # Pruned, not filtered: a kept directory's contents stay out of the golden.
    preserved = " -o ".join(
        "-path " + shlex.quote("./" + path) for path in PRESERVED_HOME_ENTRIES
    )
    return "\n".join(
        (
            "os_managed_entries=(" + shlex.join(OS_MANAGED_HOME_ENTRIES) + ")",
            "os_managed_owner="
            + shlex.quote(":".join(map(str, OS_MANAGED_FILE_OWNER))),
            "os_managed_manifest_line="
            + shlex.quote(OS_MANAGED_MANIFEST_KEY + " " + OS_MANAGED_MANIFEST_VALUE),
            "os_managed_manifest_key=" + shlex.quote(OS_MANAGED_MANIFEST_KEY),
            "required_preserved_entries=("
            + shlex.join(REQUIRED_PRESERVED_HOME_ENTRIES)
            + ")",
            "preserved_entries=(" + shlex.join(PRESERVED_HOME_ENTRIES) + ")",
            "preserved_manifest_line="
            + shlex.quote(PRESERVED_MANIFEST_KEY + " " + PRESERVED_MANIFEST_VALUE),
            "preserved_manifest_key=" + shlex.quote(PRESERVED_MANIFEST_KEY),
            _VALIDATION_FUNCTIONS.strip(),
            "list_foreign_home_entries() {",
            f'  /usr/bin/find "$home" -xdev ! -user "$capture_user" {ownership} -print',
            "}",
            "list_capture_entries() {",
            f"  /usr/bin/find . -mindepth 1 \\( {preserved} \\) -prune -o "
            "! -type s ! -type p -print0",
            "}",
        )
    )


_VALIDATION_FUNCTIONS = r"""
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
  # Older sealed baselines predate a declaration. The restore never copies a
  # preserved entry, so their captured copies stay inert and the live entries
  # are kept for them too. A present declaration may name only entries the
  # current contract keeps -- a baseline sealed before an entry was added
  # declares a subset -- and the baseline must not carry any entry kept now.
  local suffix declared
  if /usr/bin/grep -q "^$os_managed_manifest_key " "$golden$manifest_suffix"; then
    /usr/bin/grep -Fxq -- "$os_managed_manifest_line" "$golden$manifest_suffix" || return 1
    for suffix in "${os_managed_entries[@]}"; do
      lexists "$golden/$suffix" && return 1
    done
  fi
  if /usr/bin/grep -q "^$preserved_manifest_key " "$golden$manifest_suffix"; then
    declared=$(/usr/bin/grep -m 1 "^$preserved_manifest_key " "$golden$manifest_suffix")
    declared="${declared#$preserved_manifest_key }"
    for suffix in "${preserved_entries[@]}"; do
      declared="${declared//\"$suffix\"/}"
    done
    [[ "${declared//,/}" == "[]" ]] || return 1
    for suffix in "${preserved_entries[@]}"; do
      lexists "$golden/$suffix" && return 1
    done
  fi
  return 0
}
"""
