"""Static shell body for the dedicated macOS golden-capture program."""

CAPTURE_SCRIPT_BODY = r"""

lexists() {
  [[ -e "$1" || -L "$1" ]]
}

validate_home() {
  [[ "$home" != "" && "$home" != "/" && "$home" != "~" && "$home" != '$HOME' ]] \
    || return 1
  case "$home" in *'~'*|*'$'*) return 1 ;; esac
  [[ "$home" == /Users/* ]] || return 1
  local user="${home#/Users/}"
  [[ -n "$user" && "$user" != */* && "${user:l}" != "shared" ]] || return 1
  print -r -- "$user" | /usr/bin/grep -Eq '^[A-Za-z0-9._-]+$' || return 1
  [[ "${HOME:-}" == "$home" && -d "$home" && ! -L "$home" ]] || return 1
  local physical_home
  physical_home=$(builtin cd -q -- "$home" 2>/dev/null && /bin/pwd -P)
  [[ "$physical_home" == "$home" ]] || return 1
}

# The one probe that tests the Full Disk Access grant itself rather than the
# channel carrying the command. Without the grant the capture silently skips
# every privacy-protected subtree and still reports success -- which produces a
# baseline whose restore is incomplete in exactly the same invisible way.
assert_full_disk_access() {
  /bin/cat -- "$full_disk_access_probe" > /dev/null 2>&1
}

validate_destination() {
  [[ "$destination" == /* ]] || return 1
  case "$destination" in *'~'*|*'$'*|*'/../'*|*'/..') return 1 ;; esac
  # A baseline stored inside the home is destroyed by the reset it drives.
  [[ "$destination" != "$home" && "$destination" != "$home"/* ]] || return 1
  local parent="${destination:h}"
  [[ -d "$parent" && ! -L "$parent" ]] || return 1
  if lexists "$destination" || lexists "$destination$manifest_suffix" \
    || lexists "$destination$probes_suffix"; then
    failure_detail="$refusal_prefix$refusal_kind_destination_occupied $destination"
    return 1
  fi
  return 0
}

# Read-only files are valid user state. Files another account owns are not:
# the test user cannot clear them on reset or restore them afterwards, so a
# capture holding them produces a baseline that can never be reached again.
assert_home_ownership() {
  local foreign
  foreign=$(
    /usr/bin/find "$home" -xdev ! -user "$capture_user" -print 2>/dev/null |
      /usr/bin/head -1
  )
  if [[ -n "$foreign" ]]; then
    failure_detail="$refusal_prefix$refusal_kind_foreign_owner $foreign"
    return 1
  fi
  return 0
}

# Capturing a home with Yoke on it bakes Yoke into the baseline every later
# reset restores, and the reset then verifies that same state absent -- so the
# machine could never pass again. The roster is the reset's own declared-absent
# list, read from one place rather than re-enumerated here.
assert_no_yoke_residue() {
  local suffix target
  for suffix in "${yoke_absent_directories[@]}" "${yoke_absent_files[@]}"; do
    if lexists "$home/$suffix"; then
      failure_detail="$refusal_prefix$refusal_kind_residue $home/$suffix"
      return 1
    fi
  done
  for target in "${yoke_absent_temp_files[@]}"; do
    if lexists "$target"; then
      failure_detail="$refusal_prefix$refusal_kind_residue $target"
      return 1
    fi
  done
  return 0
}

copy_home() {
  /bin/mkdir -p -- "$destination" || return 1
  : > "$copy_error_log"
  while IFS= read -r -d '' entry; do
    /bin/cp -Rp "$entry" "$destination/" 2>>"$copy_error_log" || return 1
  done < <(/usr/bin/find "$home" -mindepth 1 -maxdepth 1 -print0)
  # The reset treats any restore stderr as failure and this is its mirror: a
  # capture that could not read part of the home produces a baseline missing
  # exactly that part, and nothing downstream can tell.
  [[ ! -s "$copy_error_log" ]] || return 1
  captured_entry_count=$(
    /usr/bin/find "$destination" -mindepth 1 -maxdepth 1 -print | /usr/bin/wc -l
  )
  captured_entry_count="${captured_entry_count// /}"
  [[ "$captured_entry_count" == <-> ]] || return 1
  (( captured_entry_count > 0 )) || return 1
}

# Only the directory object is sealed. The captured files keep exactly the
# modes and ACLs they had, because the restore restores modes from the golden
# and rewriting them here would make every restored home wrong.
seal_permissions() {
  /bin/chmod "$golden_directory_mode" -- "$destination"
}

write_manifest() {
  local kilobytes captured_at
  kilobytes=$(/usr/bin/du -sk -- "$destination" 2>/dev/null | /usr/bin/cut -f1)
  kilobytes="${kilobytes// /}"
  [[ "$kilobytes" == <-> ]] || return 1
  captured_kilobyte_count="$kilobytes"
  captured_at=$(/bin/date -u '+%Y-%m-%dT%H:%M:%SZ')
  {
    print -r -- "captured_at $captured_at"
    print -r -- "source_home $home"
    print -r -- "host_user $capture_user"
    print -r -- "top_level_entry_count $captured_entry_count"
    print -r -- "kilobyte_count $captured_kilobyte_count"
    print -r -- "probes_digest $probes_digest"
  } > "$destination$manifest_suffix" || return 1
  /bin/chmod "$golden_sidecar_mode" -- "$destination$manifest_suffix" || return 1
  manifest_digest=$(
    /usr/bin/shasum -a 256 "$destination$manifest_suffix" | /usr/bin/cut -d' ' -f1
  )
  [[ ${#manifest_digest} -eq 64 ]] || return 1
}

cleanup_scratch() {
  /bin/rm -f -- "$copy_error_log" 2>/dev/null || true
  return 0
}

run_capture_step() {
  capture_step="$1"
  shift
  "$@" || exit 1
}

finish() {
  finish_rc=$?
  failure_step="$capture_step"
  set +e
  trap - EXIT HUP INT TERM
  cleanup_scratch
  if (( finish_rc != 0 )); then
    print -r -- "$capture_failure_prefix$failure_step"
    if [[ -n "${failure_detail:-}" ]]; then
      print -r -- "$failure_detail"
    fi
  fi
  exit "$finish_rc"
}

capture_step="$capture_phase_validate_home"
if [[ "$#" -ne 3 ]]; then
  print -r -- "$capture_failure_prefix$capture_step"
  exit 1
fi
home="$1"
destination="$2"
probes_digest="$3"
if ! validate_home; then
  print -r -- "$capture_failure_prefix$capture_step"
  exit 1
fi
capture_user="${home#/Users/}"
copy_error_log="/tmp/yoke-machine-qa-capture-errors.$$"
captured_entry_count=0
captured_kilobyte_count=0
manifest_digest=""
failure_detail=""
trap finish EXIT
trap 'exit 1' HUP INT TERM

run_capture_step "$capture_phase_assert_full_disk_access" assert_full_disk_access
run_capture_step "$capture_phase_validate_destination" validate_destination
run_capture_step "$capture_phase_assert_home_ownership" assert_home_ownership
run_capture_step "$capture_phase_assert_no_yoke_residue" assert_no_yoke_residue
run_capture_step "$capture_phase_copy_home" copy_home
run_capture_step "$capture_phase_seal_permissions" seal_permissions
run_capture_step "$capture_phase_write_manifest" write_manifest

capture_step="$capture_phase_emit_outcomes"
print -r -- "$capture_entries_prefix$captured_entry_count"
print -r -- "$capture_kilobytes_prefix$captured_kilobyte_count"
print -r -- "$capture_manifest_digest_prefix$manifest_digest"
print -r -- "$capture_marker"
capture_step="$capture_phase_complete"
"""


__all__ = ["CAPTURE_SCRIPT_BODY"]
