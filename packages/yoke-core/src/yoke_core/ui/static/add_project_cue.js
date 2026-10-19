// The route to a project when the viewer can see none: the person's own
// harness agent adds it. The web never creates a project, so every page
// that is empty for want of one points here instead of to a form.

import { HARNESS_NAMES } from "./harness_names.js";
import { el, section } from "./universe_view_support.js";

const HARNESS_CHOICES = new Intl.ListFormat("en", { type: "disjunction" })
  .format(HARNESS_NAMES);

export const ADD_PROJECT_CUE = `Ask ${HARNESS_CHOICES} to add a project to Yoke.`;

export function addProjectCue(documentNode) {
  return el(documentNode, "p", "empty add-project-cue", ADD_PROJECT_CUE);
}

export function addProjectPanel(documentNode) {
  const panel = section(documentNode, "No projects yet");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => body.appendChild(addProjectCue(documentNode)),
  );
  return panel;
}
