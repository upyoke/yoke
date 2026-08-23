import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import { formatSessionControlTime } from "./universe_session_control_data.js";

const TIMESTAMPS = [
  ["created_at", "queued"],
  ["assigned_at", "assigned"],
  ["launching_at", "launching"],
  ["awaiting_registration_at", "awaiting registration"],
  ["attestation_consumed_at", "registration attested"],
  ["completed_at", "completed"],
];

function humanize(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

export function appendLaunchTimeline(documentNode, host, launch) {
  const timeline = el(documentNode, "ol", "session-launch-timeline");
  for (const [field, label] of TIMESTAMPS) {
    if (!launch[field]) continue;
    const item = el(documentNode, "li");
    item.appendChild(el(documentNode, "strong", null, `${label}: `));
    item.appendChild(el(
      documentNode, "span", null, formatSessionControlTime(launch[field]),
    ));
    timeline.appendChild(item);
  }
  if (launch.result_code) {
    timeline.appendChild(el(
      documentNode, "li", null, `result: ${humanize(launch.result_code)}`,
    ));
  }
  const state = String(launch.state || "unknown");
  const pill = el(
    documentNode, "span", `pill ${pillFamilyForState(state)}`, humanize(state),
  );
  host.appendChild(pill);
  host.appendChild(timeline);
}
