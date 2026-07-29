"""Static shell body for the dedicated Test Mac reset program."""

SCRIPT_BODY = r"""

lexists() {
  [[ -e "$1" || -L "$1" ]]
}

validate_home() {
  [[ "$home" != "" && "$home" != "/" && "$home" != "~" && "$home" != '$HOME' ]]
  case "$home" in *'~'*|*'$'*) return 1 ;; esac
  [[ "$home" == /Users/* ]]
  local user="${home#/Users/}"
  [[ -n "$user" && "$user" != */* && "${user:l}" != "shared" ]]
  print -r -- "$user" | /usr/bin/grep -Eq '^[A-Za-z0-9._-]+$'
  [[ "${HOME:-}" == "$home" && -d "$home" && ! -L "$home" ]]
  local physical_home
  physical_home=$(builtin cd -q -- "$home" 2>/dev/null && /bin/pwd -P)
  [[ "$physical_home" == "$home" ]]
}

assert_home_parent() {
  local parent="${1:h}"
  while [[ "$parent" != "$home" ]]; do
    [[ "$parent" == "$home"/* && ! -L "$parent" ]]
    local next="${parent:h}"
    [[ "$next" != "$parent" ]]
    parent="$next"
  done
  [[ ! -L "$home" ]]
}

remove_directory_target() {
  local target="$1"
  assert_home_parent "$target" || return 1
  /bin/rm -rf -- "$target" || return 1
  ! lexists "$target"
}

remove_file_target() {
  local target="$1"
  assert_home_parent "$target" || return 1
  [[ ! -d "$target" || -L "$target" ]] || return 1
  /bin/rm -f -- "$target" || return 1
  ! lexists "$target"
}

remove_explicit_file() {
  local target="$1"
  [[ ! -d "$target" || -L "$target" ]] || return 1
  /bin/rm -f -- "$target" || return 1
  ! lexists "$target"
}

secure_home_directory() {
  local target="$1"
  assert_home_parent "$target" || return 1
  if lexists "$target"; then
    [[ -d "$target" && ! -L "$target" ]] || return 1
  else
    /bin/mkdir "$target" || return 1
  fi
  /bin/chmod 700 "$target"
}

opaque_copy() {
  local source="$1" target="$2" temporary="$3"
  [[ -f "$source" && ! -L "$source" ]] || return 1
  if lexists "$target"; then
    [[ -f "$target" && ! -L "$target" ]] || return 1
  fi
  remove_explicit_file "$temporary" || return 1
  if ! /bin/cp "$source" "$temporary"; then
    remove_explicit_file "$temporary" || true
    return 1
  fi
  /bin/chmod 600 "$temporary" || return 1
  /bin/mv -f "$temporary" "$target" || return 1
  /bin/chmod 600 "$target"
}

preserve_tokens() {
  secure_home_directory "$token_backup_directory"
  if lexists "$stage_source"; then
    opaque_copy "$stage_source" "$stage_backup" "$stage_backup_temporary"
    stage_saved=1
  fi
  if lexists "$prod_source"; then
    opaque_copy "$prod_source" "$prod_backup" "$prod_backup_temporary"
    prod_saved=1
  fi
}

restore_tokens() {
  local failed=0
  if (( stage_saved )); then
    opaque_copy "$stage_backup" "$stage_source" "$stage_restore_temporary" || failed=1
  fi
  if (( prod_saved )); then
    opaque_copy "$prod_backup" "$prod_source" "$prod_restore_temporary" || failed=1
  fi
  return "$failed"
}

cleanup_scratch() {
  local failed=0 suffix
  remove_explicit_file "$stage_backup_temporary" || failed=1
  remove_explicit_file "$prod_backup_temporary" || failed=1
  remove_explicit_file "$stage_restore_temporary" || failed=1
  remove_explicit_file "$prod_restore_temporary" || failed=1
  for suffix in "${startup_file_suffixes[@]}"; do
    remove_explicit_file "$home/$suffix.yoke-reset-tmp" || failed=1
  done
  return "$failed"
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
  finish_failed=0
  if (( ! tokens_restored )); then
    restore_tokens || finish_failed=1
  fi
  cleanup_scratch || finish_failed=1
  if (( finish_failed )); then
    (( finish_rc == 0 )) && failure_step="$reset_phase_recovery"
    finish_rc=1
  fi
  if (( finish_rc != 0 )); then
    print -r -- "$reset_failure_prefix$failure_step"
    (( finish_failed )) && print -r -- "$reset_recovery_failure_marker"
  fi
  exit "$finish_rc"
}

preserve_evidence() {
  if lexists "$retained_evidence_root"; then
    secure_home_directory "$retained_evidence_root"
    evidence_outcome="RETAINED"
  fi
  if ! lexists "$evidence_source"; then
    return
  fi
  [[ -d "$evidence_source" && ! -L "$evidence_source" ]]
  secure_home_directory "$retained_evidence_root"
  evidence_container=$(
    /usr/bin/mktemp -d "$retained_evidence_root/reset.XXXXXX"
  )
  [[ -d "$evidence_container" && ! -L "$evidence_container" ]]
  /bin/chmod 700 "$evidence_container"
  if ! /bin/mv "$evidence_source" \
    "$evidence_container/installer-smoke-evidence"; then
    /bin/rmdir "$evidence_container" 2>/dev/null || true
    return 1
  fi
  evidence_outcome="MOVED"
}

remove_registered_state() {
  [[ ! -L "$home/.yoke" ]]
  preserve_evidence
  remove_directory_target "$home/.yoke"
  local suffix target
  for suffix in "${reset_relative_directories[@]}"; do
    remove_directory_target "$home/$suffix"
  done
  for suffix in "${tool_file_suffixes[@]}"; do
    remove_file_target "$home/$suffix"
  done
  for target in "${reset_temp_files[@]}" "$stage_source" "$prod_source"; do
    remove_explicit_file "$target"
  done
  target="$home/code"
  if lexists "$target"; then
    [[ -d "$target" && ! -L "$target" ]]
    assert_home_parent "$target"
    /usr/bin/find "$target" -mindepth 1 -maxdepth 1 \
      -exec /bin/rm -rf -- {} +
    if /usr/bin/find "$target" -mindepth 1 -maxdepth 1 -print -quit \
      | /usr/bin/grep -q .; then
      return 1
    fi
  fi
}

clean_startup_file() {
  local file="$1" temporary="$1.yoke-reset-tmp" mode
  if ! lexists "$file"; then
    return
  fi
  assert_home_parent "$file"
  [[ -f "$file" && ! -L "$file" ]]
  mode=$(/usr/bin/stat -f '%Lp' "$file")
  print -r -- "$mode" | /usr/bin/grep -Eq '^[0-7]{3,4}$'
  remove_explicit_file "$temporary"
  /usr/bin/awk \
    -v managed_begin="$managed_begin" \
    -v managed_end="$managed_end" \
    -v legacy_begin="$legacy_baseline_begin" \
    -v legacy_end="$legacy_baseline_end" \
    -v absolute_bin="$tool_bin_dir" \
    -v home_bin="$tool_bin_home_reference" '
    index($0, managed_begin) || index($0, legacy_begin) {skip=1; next}
    index($0, managed_end) || index($0, legacy_end) {skip=0; next}
    /uv was installed/ {next}
    skip {next}
    (index($0, absolute_bin) || index($0, home_bin)) &&
      (/PATH/ || /\/env"/) {next}
    {print}
  ' "$file" > "$temporary"
  /bin/chmod "$mode" "$temporary"
  /bin/mv -f "$temporary" "$file"
  /usr/bin/awk \
    -v managed_begin="$managed_begin" \
    -v managed_end="$managed_end" \
    -v legacy_begin="$legacy_baseline_begin" \
    -v legacy_end="$legacy_baseline_end" \
    -v absolute_bin="$tool_bin_dir" \
    -v home_bin="$tool_bin_home_reference" '
    index($0, managed_begin) || index($0, managed_end) {bad=1}
    index($0, legacy_begin) || index($0, legacy_end) {bad=1}
    /uv was installed/ {bad=1}
    (index($0, absolute_bin) || index($0, home_bin)) &&
      (/PATH/ || /\/env"/) {bad=1}
    END {exit bad}
  ' "$file"
}

clean_startup_files() {
  local suffix
  for suffix in "${startup_file_suffixes[@]}"; do
    clean_startup_file "$home/$suffix"
  done
}

uninstall_homebrew_uv() {
  if [[ -x "$homebrew_path" ]] \
    && "$homebrew_path" list --versions uv >/dev/null 2>&1; then
    "$homebrew_path" uninstall uv >/dev/null 2>&1
    ! "$homebrew_path" list --versions uv >/dev/null 2>&1
  fi
}

verify_shell_resolution() {
  local flag
  for flag in -lic -c; do
    PATH="$clean_shell_path" "$shell_path" "$flag" '
      tool_bin_dir="$1"
      shift
      for tool in "$@"; do
        if command -v "$tool" >/dev/null 2>&1; then
          exit 41
        fi
      done
      if printf "%s\n" "$PATH" | /usr/bin/tr ":" "\n" \
        | /usr/bin/grep -Fx "$tool_bin_dir" >/dev/null; then
        exit 42
      fi
    ' yoke-reset "$tool_bin_dir" "${tools[@]}" >/dev/null 2>&1
  done
  for suffix in "${tool_file_suffixes[@]}"; do
    if lexists "$home/$suffix"; then
      return 1
    fi
  done
}

reset_step="$reset_phase_validate_home"
if [[ "$#" -ne 1 ]]; then
  print -r -- "$reset_failure_prefix$reset_step"
  exit 1
fi
home="$1"
if ! validate_home; then
  print -r -- "$reset_failure_prefix$reset_step"
  exit 1
fi
tool_bin_dir="$home/$tool_bin_suffix"
token_backup_directory="$home/$token_backup_name"
stage_backup="$token_backup_directory/$stage_backup_name"
prod_backup="$token_backup_directory/$prod_backup_name"
stage_backup_temporary="$token_backup_directory/.$stage_backup_name.reset-tmp"
prod_backup_temporary="$token_backup_directory/.$prod_backup_name.reset-tmp"
stage_restore_temporary="$stage_source.reset-tmp"
prod_restore_temporary="$prod_source.reset-tmp"
evidence_source="$home/$evidence_source_suffix"
retained_evidence_root="$home/$retained_evidence_name"
stage_saved=0
prod_saved=0
tokens_restored=0
evidence_outcome="ABSENT"
evidence_container=""
trap finish EXIT
trap 'exit 1' HUP INT TERM

run_reset_step "$reset_phase_preserve_tokens" preserve_tokens
run_reset_step "$reset_phase_remove_registered_state" remove_registered_state
run_reset_step "$reset_phase_uninstall_homebrew_uv" uninstall_homebrew_uv
run_reset_step "$reset_phase_clean_startup_files" clean_startup_files
run_reset_step "$reset_phase_verify_shell_resolution" verify_shell_resolution
run_reset_step "$reset_phase_restore_tokens" restore_tokens
tokens_restored=1
run_reset_step "$reset_phase_cleanup_scratch" cleanup_scratch

stage_outcome="ABSENT"
prod_outcome="ABSENT"
(( stage_saved )) && stage_outcome="RESTORED"
(( prod_saved )) && prod_outcome="RESTORED"
reset_step="$reset_phase_emit_outcomes"
print -r -- "YOKE_TOKEN_STAGE_$stage_outcome"
print -r -- "YOKE_TOKEN_PROD_$prod_outcome"
print -r -- "YOKE_INSTALLER_EVIDENCE_$evidence_outcome"
print -r -- "$full_reset_marker"
reset_step="$reset_phase_complete"
"""


__all__ = ["SCRIPT_BODY"]
