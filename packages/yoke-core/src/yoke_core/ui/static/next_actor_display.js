// The server owns classification; older servers can omit this projection.
import { el } from "./universe_view_support.js";

const LABELS = {
  this_session: "this session",
  operator: "operator",
  parent_or_steering: "parent or steering",
  another_item: "another item",
  ci_or_deploy: "CI or deployment",
  nobody: "nobody",
};

export function nextActorText(next) {
  if (!next?.actor) return "";
  const people = (next.people || []).map((person) => person.name).filter(Boolean);
  const who = people.length ? people.join(", ") : LABELS[next.actor] || next.actor;
  const reason = String(next.reason || "").replaceAll("_", " ");
  return `Next: ${who}${reason ? ` · ${reason}` : ""}`;
}

export function appendNextActor(documentNode, host, next) {
  const text = nextActorText(next);
  if (!text) return;
  const line = el(documentNode, "div", "next-actor", text);
  if (next.since) line.title = `Since ${next.since}`;
  if (next.recovery) line.appendChild(el(documentNode, "span", "next-actor-recovery", ` · ${next.recovery}`));
  host.appendChild(line);
}
