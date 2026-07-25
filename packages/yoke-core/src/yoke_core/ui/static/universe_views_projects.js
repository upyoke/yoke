import { renderTable, section } from "./universe_view_support.js";

export function renderProjectsView(context, main) {
  const panel = section(context.document, "Projects");
  main.replaceChildren(panel);
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: { rows: context.projects() } } },
    (body) => {
      renderTable(body, context.projects(), [
        { label: "id", value: (row) => row.id },
        { label: "name", value: (row) => row.name },
        { label: "slug", value: (row) => row.slug },
      ], "no projects yet");
    },
  );
}
