"""Process-table helpers for the dedicated Test Mac reset program."""

REAP_FUNCTIONS = r"""
reap_candidate_pids() {
  local pid command_line
  /bin/ps -ww -u "$reap_user" -o pid=,command= 2>/dev/null |
  while read -r pid command_line; do
    [[ "$pid" == <-> ]] || continue
    case "$command_line" in
      *"$reap_marker_anchor"*"$reap_marker_suffix"*|*"$reap_onboard_anchor"*) ;;
      *) continue ;;
    esac
    print -r -- "$pid"
  done
}

reap_descendant_pids() {
  local parent="$1" child
  for child in $(/usr/bin/pgrep -P "$parent" 2>/dev/null || true); do
    reap_descendant_pids "$child"
  done
  print -r -- "$parent"
}

reap_processes() {
  local pid signal descendants
  reap_target_count=$(reap_candidate_pids | /usr/bin/wc -l | tr -d ' ' || true)
  [[ "$reap_target_count" == <-> ]] || reap_target_count=0
  reap_failed_count=0
  typeset -A reaped_seen
  reaped_seen=()
  for pid in ${(f)"$(reap_candidate_pids)"}; do
    [[ "$pid" == <-> ]] || continue
    (( pid != $$ && ! ${+reaped_seen[$pid]} )) || continue
    for signal in TERM KILL; do
      descendants=$(reap_descendant_pids "$pid")
      [[ -n "$descendants" ]] || break
      for descendant in ${(f)descendants}; do
        /bin/kill "-$signal" "$descendant" 2>/dev/null || true
        reaped_seen[$descendant]=1
      done
      /bin/sleep 1
    done
    if /bin/kill -0 "$pid" 2>/dev/null; then
      reap_failed_count=$((reap_failed_count + 1))
    fi
  done
}

count_reap_matches() {
  reap_match_count=$(reap_candidate_pids | /usr/bin/wc -l | tr -d ' ' || true)
  [[ "$reap_match_count" == <-> ]] || reap_match_count=0
}

record_load_average() {
  load_average_1min=$(
    /usr/bin/uptime |
      /usr/bin/sed -E 's/.*load averages?: //' |
      /usr/bin/awk '{print $1}'
  )
  cpu_count=$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || print 0)
}

load_exceeds_capacity() {
  [[ -n "$load_average_1min" && "$cpu_count" == <-> ]] || return 1
  (( cpu_count > 0 && load_average_1min > cpu_count ))
}
"""


__all__ = ["REAP_FUNCTIONS"]
