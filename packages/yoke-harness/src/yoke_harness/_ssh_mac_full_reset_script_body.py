"""Static shell body for the dedicated Test Mac reset program."""

SCRIPT_BODY = r"""

lexists() {
  [[ -e "$1" || -L "$1" ]]
}

# Every check returns explicitly. ERREXIT is disabled inside a function called
# from a conditional, so a bare test only decides the outcome when it happens to
# be the last line, which silently turns the checks after it into commentary.
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
# channel carrying the command. Without the grant the restore silently skips
# every privacy-protected subtree and still reports success.
assert_full_disk_access() {
  /bin/cat -- "$full_disk_access_probe" > /dev/null 2>&1
}

validate_golden() {
  [[ "$golden" == /* ]] || return 1
  case "$golden" in *'~'*|*'$'*|*'/../'*|*'/..') return 1 ;; esac
  [[ -d "$golden" && ! -L "$golden" ]] || return 1
  local physical_golden
  physical_golden=$(builtin cd -q -- "$golden" 2>/dev/null && /bin/pwd -P)
  [[ "$physical_golden" == "$golden" ]] || return 1
  # A baseline stored inside the home is destroyed by the clear it drives.
  [[ "$golden" != "$home" && "$golden" != "$home"/* ]] || return 1
  [[ -f "$golden$manifest_suffix" && ! -L "$golden$manifest_suffix" ]] || return 1
  golden_entry_count=$(
    /usr/bin/find "$golden" -mindepth 1 -maxdepth 1 -print | /usr/bin/wc -l
  )
  golden_entry_count="${golden_entry_count// /}"
  [[ "$golden_entry_count" == <-> ]] || return 1
  (( golden_entry_count > 0 )) || return 1
}

# rm reports "Permission denied" for Desktop, Music, Pictures, Public and
# Library/Preferences because a standard macOS ACL, group:everyone deny delete,
# forbids removing the DIRECTORY while still allowing its contents to be
# cleared. Those reports are cosmetic and a clear that aborted on rm's exit
# status would fail on a correct run, so the clear phase deliberately ignores
# them. The restore phase does the opposite and treats any stderr as failure.
clear_home() {
  clear_home_levels
  restored_entry_count=0
  return 0
}

restore_golden() {
  : > "$restore_error_log"
  restore_golden_levels
  # A restore that cannot prove it copied everything is the enumeration problem
  # this design exists to escape, reintroduced at the last step. Every skipped
  # entry is reported, so a report that was discarded is a restore that lied.
  [[ ! -s "$restore_error_log" ]] || return 1
  restored_entry_count=$(
    /usr/bin/find "$home" -mindepth 1 -maxdepth 1 -print | /usr/bin/wc -l
  )
  restored_entry_count="${restored_entry_count// /}"
  [[ "$restored_entry_count" == <-> ]] || return 1
}

# The tools must not resolve; the directory holding them is NOT the test. A real
# user's own command-line tools install into that same directory and put it on
# the login PATH, so demanding it be absent would fail every correctly restored
# machine and would be measuring the user's toolchain, not Yoke's residue.
shell_surface_is_clean() {
  local flag="$1"
  PATH="$clean_shell_path" "$shell_path" "$flag" '
    for tool in "$@"; do
      if command -v "$tool" >/dev/null 2>&1; then
        exit 41
      fi
    done
  ' yoke-reset "${tools[@]}" >/dev/null 2>&1
}

verify_restored_home() {
  local suffix target flag
  for suffix in "${preserved_entries[@]}"; do
    lexists "$home/$suffix" || return 1
  done
  for suffix in "${yoke_absent_directories[@]}" "${yoke_absent_files[@]}"; do
    if lexists "$home/$suffix"; then
      return 1
    fi
  done
  for target in "${yoke_absent_temp_files[@]}"; do
    if lexists "$target"; then
      return 1
    fi
  done
  golden_missing_count=$(
    /usr/bin/find "$golden" -mindepth 1 -maxdepth 1 -print |
      while IFS= read -r captured; do
        lexists "$home/${captured:t}" || print -r -- "${captured:t}"
      done | /usr/bin/wc -l
  )
  golden_missing_count="${golden_missing_count// /}"
  [[ "$golden_missing_count" == <-> ]] || return 1
  (( golden_missing_count == 0 )) || return 1
  # Both surfaces are checked explicitly: a login shell reads the restored
  # startup files and an SSH shell does not, so a Yoke entry surviving in one
  # is invisible from the other.
  for flag in -lic -c; do
    if shell_surface_is_clean "$flag"; then
      continue
    fi
    return 1
  done
}

cleanup_scratch() {
  /bin/rm -f -- "$restore_error_log" 2>/dev/null || true
  return 0
}

run_reset_step() {
  reset_step="$1"
  shift
  "$@" || exit 1
}

finish() {
  finish_rc=$?
  failure_step="$reset_step"
  set +e
  trap - EXIT HUP INT TERM
  cleanup_scratch
  if (( finish_rc != 0 )); then
    print -r -- "$reset_failure_prefix$failure_step"
    if [[ -n "${reap_failure_detail:-}" ]]; then
      print -r -- "$reap_failure_detail"
    fi
  fi
  exit "$finish_rc"
}

reset_step="$reset_phase_validate_home"
if [[ "$#" -ne 2 ]]; then
  print -r -- "$reset_failure_prefix$reset_step"
  exit 1
fi
home="$1"
golden="$2"
if ! validate_home; then
  print -r -- "$reset_failure_prefix$reset_step"
  exit 1
fi
tool_bin_dir="$home/$tool_bin_suffix"
restore_error_log="/tmp/yoke-machine-qa-restore-errors.$$"
golden_entry_count=0
restored_entry_count=0
golden_missing_count=0
reap_user="${home#/Users/}"
reap_target_count=0
reap_failed_count=0
reap_match_count=0
load_average_1min=""
cpu_count=0
reap_failure_detail=""
trap finish EXIT
trap 'exit 1' HUP INT TERM

run_reset_step "$reset_phase_assert_full_disk_access" assert_full_disk_access
run_reset_step "$reset_phase_validate_golden" validate_golden
run_reset_step "$reset_phase_reap_processes" reap_processes
run_reset_step "$reset_phase_clear_home" clear_home
run_reset_step "$reset_phase_restore_golden" restore_golden
run_reset_step "$reset_phase_verify_restored_home" verify_restored_home

reset_step="$reset_phase_emit_outcomes"
count_reap_matches
record_load_average
print -r -- "$restored_entries_prefix$restored_entry_count"
if [[ -z "$load_average_1min" ]] \
  || (( reap_failed_count > 0 || reap_match_count > 0 )) \
  || load_exceeds_capacity; then
  reset_step="$reset_phase_reap_processes"
  reap_failure_detail="$reap_failed_count $reap_match_count ${load_average_1min:-0}"
  exit 1
fi
print -r -- "$reset_process_reaped_prefix$reap_target_count"
print -r -- "$reset_load_average_prefix$load_average_1min"
print -r -- "$full_reset_marker"
reset_step="$reset_phase_complete"
"""


__all__ = ["SCRIPT_BODY"]
