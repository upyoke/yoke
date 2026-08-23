"""Bounded lifetime for one interactive terminal-recipe entry surface."""

from __future__ import annotations

import shlex


def wrapped_entry_surface(
    entry_surface: str,
    status_path: str,
    *,
    watchdog_seconds: int,
) -> str:
    """Run one entry surface in the background and reap it if it overruns.

    Recipes already carry a wall-clock budget. This remote backstop exists
    because a full-screen installer TUI that never exits would otherwise
    hold its login session open after the controller is gone.
    """
    quoted_status = shlex.quote(status_path)
    seconds = max(1, int(watchdog_seconds))
    return f"""set +e
yoke_reap_tree() {{
  yk_pids=" $1 "
  yk_round=0
  while [ "$yk_round" -lt 8 ]; do
    yk_added=""
    for yk_p in $yk_pids; do
      for yk_c in $(ps -axo pid=,ppid= 2>/dev/null | awk -v p="$yk_p" '$2 == p {{print $1}}'); do
        case "$yk_pids" in
          *" $yk_c "*) ;;
          *) yk_pids="$yk_pids$yk_c " yk_added=1 ;;
        esac
      done
    done
    [ -n "$yk_added" ] || break
    yk_round=$((yk_round + 1))
  done
  for yk_p in $yk_pids; do kill -9 "$yk_p" 2>/dev/null; done
}}
( {entry_surface}; printf '%s\\n' "$?" > {quoted_status} ) &
yk_entry=$!
( yk_left={seconds}
  while [ "$yk_left" -gt 0 ]; do
    sleep 1
    yk_left=$((yk_left - 1))
    kill -0 "$yk_entry" 2>/dev/null || break
  done
  if kill -0 "$yk_entry" 2>/dev/null; then
    yoke_reap_tree "$yk_entry"
  fi
) &
yk_watch=$!
wait "$yk_entry" 2>/dev/null
if ! [ -f {quoted_status} ]; then
  printf '%s\\n' 124 > {quoted_status}
fi
kill "$yk_watch" 2>/dev/null
wait "$yk_watch" 2>/dev/null
"""


__all__ = ["wrapped_entry_surface"]
