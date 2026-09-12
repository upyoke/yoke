// The dashboard's one "how long ago" convention: minute granularity rolling
// over to hours past an hour and days past 48 hours. Every "X ago" display
// on the card (age, idle recency, claim held, QA result age, …) reuses this
// — and its click/keyboard absolute-time toggle via `relativeTime` below —
// rather than authoring a per-card formatter. `preciseAge` further down is
// the deliberate seconds-granular exception for facts that change faster
// than a minute (a relay heartbeat), not a second convention to choose
// between.
export function relativeAge(value, now = Date.now()) {
  if (!value) return "recently";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return String(value);
  const elapsedSeconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (elapsedSeconds < 60) return "now";
  const minutes = Math.floor(elapsedSeconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

// Compact magnitudes take "ago"; words that already read naturally do not.
// Keeping that grammar here prevents callers from producing "now ago" or
// "recently ago" while preserving the dashboard's familiar "5m ago" form.
export function relativeAgePhrase(value, now = Date.now()) {
  const age = relativeAge(value, now);
  return /^\d+[mhd]$/.test(age) ? `${age} ago` : age;
}

// Seconds-granular age, for a fact that changes faster than a minute: a relay
// heartbeat is seconds old almost always, and "now" hides whether it is still
// arriving. `relativeAge` stays the default everywhere a minute is the
// smallest interval that carries meaning.
export function preciseAge(value, now = Date.now()) {
  const timestamp = Date.parse(String(value || ""));
  if (Number.isNaN(timestamp)) return null;
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export function isInstantRelativeTime(value, now = Date.now()) {
  return relativeAge(value, now) === "now";
}

// The viewer's time-zone preference (Profile → Preferences). Empty means
// Automatic: the browser's own zone. Set once from the profile read and
// again when the person changes it, so every absolute time follows.
let displayTimeZone = "";

export function setDisplayTimeZone(zone) {
  displayTimeZone = String(zone || "");
}

export function displayTimeZoneValue() {
  return displayTimeZone;
}

function absoluteTime(value) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return String(value || "");
  const options = { dateStyle: "medium", timeStyle: "short" };
  if (displayTimeZone) options.timeZone = displayTimeZone;
  try {
    return timestamp.toLocaleString(undefined, options);
  } catch (rangeError) {
    // An unknown zone name must not blank every time on the page.
    delete options.timeZone;
    return timestamp.toLocaleString(undefined, options);
  }
}

export function relativeTime(
  documentNode, value, now = Date.now(),
  { instantText = "now", relativeAgeFn = relativeAge } = {},
) {
  const time = documentNode.createElement("time");
  const timestamp = new Date(value).getTime();
  const relativeText = (referenceTime = Date.now()) => {
    const age = relativeAgeFn(value, referenceTime);
    return age === "now" ? instantText : age;
  };
  const relative = relativeText(now);
  const absolute = absoluteTime(value);
  time.className = "ago";
  time.textContent = relative;
  // Deliberately the browser's own title rather than the shared tooltip: this
  // element's own click and Enter/Space toggle already swap the visible text
  // to this absolute value, and aria-label carries it, so the fact is not
  // hover-only and the swap would replace an attached bubble anyway.
  time.title = absolute;
  time.tabIndex = 0;
  time.setAttribute("role", "button");
  time.setAttribute("aria-pressed", "false");
  time.setAttribute("aria-label", absolute || relative);
  if (!Number.isNaN(timestamp)) {
    time.setAttribute("datetime", new Date(timestamp).toISOString());
    time.setAttribute("data-ms", String(timestamp));
  }
  const toggle = () => {
    const showingAbsolute = time.textContent === absolute;
    time.textContent = showingAbsolute ? relativeText() : absolute;
    time.setAttribute("aria-pressed", String(!showingAbsolute));
    time.setAttribute(
      "aria-label",
      showingAbsolute ? absolute || relative : `${absolute}; relative time ${relative}`,
    );
  };
  time.addEventListener("click", toggle);
  time.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    toggle();
  });
  return time;
}
