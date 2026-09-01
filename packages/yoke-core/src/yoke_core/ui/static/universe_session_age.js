import {
  focusAttribution,
  topRenderedClaim,
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
  const topClaim = topRenderedClaim(row);
  if (topClaim) {
    add(
      "claim held ",
      topClaim.claimed_at || row.claim_started_at || row.activity_at,
    );
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  } else if (attributed) {
    add(attributed === "lane" ? "worktree attached " : "filed ", row.activity_at);
    age.appendChild(el(documentNode, "span", "session-age-separator", " · "));
  }
  // The server still owns alive-versus-stale classification. Activity age
  // only distinguishes a recently active session from one that is alive but quiet.
  const instantActivity = isInstantRelativeTime(row.activity_at, now);
  const staleNow = row.liveness === "stale" && instantActivity;
  const activityState = row.liveness === "active" && !instantActivity
    ? "idle"
    : row.liveness || "unknown";
  add(staleNow ? "stale · activity " : `${activityState} `,
    row.activity_at, staleNow ? "just now" : undefined);
  body.appendChild(age);
}
