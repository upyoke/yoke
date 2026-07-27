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

function absoluteTime(value) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return String(value || "");
  return timestamp.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function relativeTime(documentNode, value, now = Date.now()) {
  const time = documentNode.createElement("time");
  const timestamp = new Date(value).getTime();
  const relative = relativeAge(value, now);
  const absolute = absoluteTime(value);
  time.className = "ago";
  time.textContent = relative;
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
    time.textContent = showingAbsolute ? relativeAge(value) : absolute;
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
