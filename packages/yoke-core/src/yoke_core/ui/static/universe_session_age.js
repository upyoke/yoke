import {
  focusAttribution,
  ownsFocusedItem,
} from "./universe_sessions_holdings.js";
import { isInstantRelativeTime, relativeTime } from "./universe_time.js";
import { el } from "./universe_view_support.js";

export function appendSessionAge(documentNode, body, row) {
  const age = el(documentNode, "div", "session-age");
  const now = Date.now();
  const add = (prefix, timestamp, instantText) => {
    if (prefix) {
      age.appendChild(el(documentNode, "span", "session-age-prefix", prefix));
    }
    age.appendChild(relativeTime(documentNode, timestamp, now, { instantText }));
  };
  const startedAt = row.offered_at;
  if (startedAt && !Number.isNaN(new Date(startedAt).getTime())) {
    const instantStart = isInstantRelativeTime(startedAt, now);
    add(instantStart ? "created " : "", startedAt, "just now");
    if (!instantStart) {
      age.appendChild(el(documentNode, "span", "session-age-prefix", " old"));
    }
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  }
  const attributed = focusAttribution(row);
  if (row.current_item && ownsFocusedItem(row)) {
    add("claim held ", row.claim_started_at || row.activity_at);
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  } else if (attributed) {
    add(attributed === "lane" ? "worktree attached " : "filed ", row.activity_at);
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  }
  // The server classified this session against an executor-aware TTL; the
  // card reports that state without recalculating it from elapsed time.
  const staleNow = row.liveness === "stale"
    && isInstantRelativeTime(row.activity_at, now);
  add(staleNow ? "stale · activity " : `${row.liveness || "unknown"} `,
    row.activity_at, staleNow ? "just now" : undefined);
  body.appendChild(age);
}
