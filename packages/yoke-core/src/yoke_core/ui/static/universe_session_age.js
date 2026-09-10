import {
  focusAttribution,
  topRenderedClaim,
} from "./universe_sessions_holdings.js";
import { isInstantRelativeTime, relativeTime } from "./universe_time.js";
import { el } from "./universe_view_support.js";

// How often the "active now" / "idle Xm" text repaints itself so a reader
// watching the card sees the one-minute boundary cross without reloading.
const ACTIVITY_REFRESH_MS = 5_000;

// Elapsed whole minutes for the activity line, deliberately not the shared
// `relativeAge` — that helper rolls over to hours/days, but this line always
// reads "idle Xm" no matter how long the session has been quiet. A
// timestamp that fails to parse (missing, or a stray literal like "now")
// never counts as instant, so it can never render "active now".
function activityMinutesAge(value, now = Date.now()) {
  const parsed = Date.parse(String(value ?? ""));
  if (Number.isNaN(parsed)) return "recently";
  const elapsedMs = Math.max(0, now - parsed);
  if (elapsedMs < 60_000) return "now";
  return `${Math.floor(elapsedMs / 60_000)}m`;
}

// Recency wording for the observed-activity timestamp, live: "active now"
// while under a minute old, "idle Xm" once past it. Reuses relativeTime's
// click/keyboard toggle to absolute time, driven by activityMinutesAge so
// toggling back to relative never disagrees with the periodic repaint.
function appendActivityStatus(documentNode, age, timestamp) {
  const time = relativeTime(documentNode, timestamp, Date.now(), {
    instantText: "now", relativeAgeFn: activityMinutesAge,
  });
  const prefix = el(documentNode, "span", "session-age-prefix", "");
  const paint = () => {
    const instant = activityMinutesAge(timestamp, Date.now()) === "now";
    prefix.textContent = instant ? "active " : "idle ";
    // A reader who toggled the time open to its absolute value is inspecting
    // it; a repaint must not overwrite that out from under them.
    if (time.getAttribute("aria-pressed") !== "true") {
      time.textContent = instant ? "now" : activityMinutesAge(timestamp, Date.now());
    }
  };
  paint();
  age.appendChild(prefix);
  age.appendChild(time);
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
  // Activity recency is duration only. Primary status lives on the identity
  // pill; this line answers "active now" or "idle Xm" and keeps answering it
  // as time passes.
  appendActivityStatus(documentNode, age, row.activity_at);
  body.appendChild(age);
}
