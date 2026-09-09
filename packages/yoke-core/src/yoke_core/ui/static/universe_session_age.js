import {
  focusAttribution,
  topRenderedClaim,
} from "./universe_sessions_holdings.js";
import { isInstantRelativeTime, relativeTime } from "./universe_time.js";
import { el } from "./universe_view_support.js";

// The prior item, the moment it ended, and why — the facts an ended session
// has where a live one has a heartbeat. They ride the same timing region and
// the same fact-line typography, so an ended card is the live card with
// different values rather than a second, simpler card.
function appendEndedFacts(documentNode, body, row) {
  const prior = row.recent_item_title || row.focus || row.recent_item;
  if (prior) body.appendChild(el(
    documentNode, "div", "fact-line session-history-prior",
    row.recent_item ? `${prior} · ${row.recent_item}` : prior,
  ));
  if (row.termination_reason) body.appendChild(el(
    documentNode, "div", "fact-line session-history-reason",
    `Reason: ${row.termination_reason}`,
  ));
}

export function appendSessionAge(documentNode, body, row) {
  const age = el(documentNode, "div", "session-age");
  const now = Date.now();
  const add = (prefix, timestamp, instantText) => {
    if (prefix) {
      age.appendChild(el(documentNode, "span", "session-age-prefix", prefix));
    }
    age.appendChild(relativeTime(documentNode, timestamp, now, { instantText }));
  };
  if (String(row.liveness || "") === "ended") {
    appendEndedFacts(documentNode, body, row);
    // An ended session's activity age IS the moment it ended, so the region
    // names that once rather than repeating it as a second duration. An end
    // nobody recorded a time for says so, rather than reading as recent.
    const cause = row.ended_cause === "killed" ? "killed " : "ended ";
    const endedAt = row.ended_at || row.terminated_at || row.activity_at;
    if (endedAt) add(cause, endedAt);
    else age.appendChild(el(
      documentNode, "span", "session-age-prefix", `${cause}· time unavailable`,
    ));
    body.appendChild(age);
    return;
  }
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
  // Activity age is duration only. Primary status lives on the identity pill.
  add("activity ", row.activity_at);
  body.appendChild(age);
}
