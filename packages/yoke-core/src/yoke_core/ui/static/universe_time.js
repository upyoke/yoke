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
