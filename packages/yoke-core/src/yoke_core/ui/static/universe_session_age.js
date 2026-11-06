import {
  focusAttribution,
  topRenderedClaim,
} from "./universe_sessions_holdings.js";
import { isInstantRelativeTime, relativeAge, relativeTime } from "./universe_time.js";
import { el } from "./universe_view_support.js";
import { formatInstant } from "./timestamps.js";

// Refresh tool age as it crosses unit boundaries.
const ACTIVITY_REFRESH_MS = 5_000;

// Only a qualified tool clock supplies recency.
function activityAge(value, now = Date.now()) {
  return value == null ? "unavailable"
    : isInstantRelativeTime(value, now) ? "<1m" : relativeAge(value, now);
}

function optionalActivityInstant(value) {
  if (value == null) return null;
  try {
    return formatInstant(value);
  } catch {
    return null;
  }
}

// Tool recency remains independent of heartbeat and session intent.
function appendActivityStatus(documentNode, age, timestamp) {
  const activityTimestamp = optionalActivityInstant(timestamp);
  if (!activityTimestamp) {
    age.appendChild(el(documentNode, "span", "session-age-prefix", "last tool unavailable"));
    return;
  }
  const time = relativeTime(documentNode, activityTimestamp, Date.now(), {
    instantText: "<1m", relativeAgeFn: activityAge,
  });
  const prefix = el(documentNode, "span", "session-age-prefix", "last tool ");
  const paint = () => {
    if (time.getAttribute("aria-pressed") !== "true") {
      time.textContent = activityAge(activityTimestamp, Date.now());
    }
  };
  paint();
  age.appendChild(prefix);
  age.appendChild(time);
  age.appendChild(el(documentNode, "span", "session-age-suffix", " ago"));
  // Self-disposing: once `age` leaves the live document (its card was
  // replaced by a later render) the next tick clears itself instead of
  // repainting a detached card forever. `.unref()` keeps a Node test runner
  // from hanging on an interval nothing ever clears synchronously.
  const timer = setInterval(() => {
    if (age.isConnected === false) {
      clearInterval(timer);
      return;
    }
    paint();
  }, ACTIVITY_REFRESH_MS);
  if (typeof timer.unref === "function") timer.unref();
}

// Why it ended stays on the shared fact-line. The last item it held is the
// holdings panel, not a summary parsed onto this line.
function appendEndedFacts(documentNode, body, row) {
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
  // Tool recency is independent of presence, intent and heartbeat.
  appendActivityStatus(documentNode, age, row.last_tool_call_at);
  body.appendChild(age);
}
