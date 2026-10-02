import { callFunction, el } from "./universe_view_support.js";
import { labelledControl, presentSessionControlFailure } from "./universe_session_control_data.js";

export function machineAccessCard(context, result, reload) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "machine-detail-card");
  card.appendChild(el(documentNode, "h3", null, "Machine access"));
  const current = result.machine.access?.use || {};
  const retired = Boolean(result.machine.retired_at);
  const mode = el(documentNode, "select", "machine-access-select");
  for (const [value, label] of [
    ["owner_only", "Only the owner"], ["actors", "Selected people and actors"],
    ["project_role", "People with a project role"], ["universe", "Everyone in this universe"],
  ]) {
    const option = el(documentNode, "option", null, label);
    option.value = value;
    mode.appendChild(option);
  }
  mode.value = current.mode || "owner_only";
  card.appendChild(labelledControl(documentNode, "Who can use this machine", mode));
  const actorField = el(documentNode, "fieldset", "machine-access-actors");
  actorField.appendChild(el(documentNode, "legend", null, "People and actors"));
  const actorChoices = el(documentNode, "div", "machine-access-choices");
  actorField.appendChild(actorChoices);
  const selectedActors = new Set((current.actor_ids || []).map(Number));
  const project = el(documentNode, "select", "machine-access-input");
  const projects = context.projects?.() || [];
  const placeholder = el(documentNode, "option", null, "Choose a project");
  placeholder.value = "";
  project.appendChild(placeholder);
  for (const entry of projects) {
    const option = el(documentNode, "option", null, entry.name || entry.slug);
    option.value = String(entry.id);
    project.appendChild(option);
  }
  if (current.project_id && !projects.some((entry) => Number(entry.id) === Number(current.project_id))) {
    const unknown = el(documentNode, "option", null, `Unavailable project #${current.project_id}`);
    unknown.value = String(current.project_id);
    project.appendChild(unknown);
  }
  project.value = current.project_id ? String(current.project_id) : "";
  const role = el(documentNode, "input", "machine-access-input");
  role.value = current.role || "";
  const projectField = labelledControl(documentNode, "Project", project);
  const roleField = labelledControl(documentNode, "Required project role", role);
  const status = el(documentNode, "p", "machine-access-status");
  status.setAttribute("role", "status");
  const save = el(documentNode, "button", "item-button", "Save access");
  save.type = "button";
  for (const node of [actorField, projectField, roleField, status, save]) card.appendChild(node);
  let busy = false;
  let loaded = false;
  let loading = false;
  const update = () => {
    actorField.hidden = mode.value !== "actors";
    projectField.hidden = roleField.hidden = mode.value !== "project_role";
    for (const control of [mode, project, role, ...actorChoices.children].flatMap((node) =>
      node.tagName === "LABEL" ? [...node.children].filter((child) => child.tagName === "INPUT") : [node])) {
      control.disabled = busy || retired;
    }
    save.disabled = busy || retired || (mode.value === "actors" && !loaded);
  };
  const loadActors = async () => {
    if (loaded || loading || retired) return;
    loading = true;
    actorChoices.textContent = "Loading people and actors…";
    update();
    try {
      const response = await callFunction(context.client, "actors.roster", {});
      if (response.status !== 200 || !response.envelope?.success) throw response;
      if (!context.isMounted()) return;
      const rows = response.envelope.result.rows || [];
      actorChoices.replaceChildren();
      const choices = [...rows];
      for (const id of selectedActors) {
        if (!choices.some((entry) => Number(entry.id) === id)) choices.push({ id, name: `Actor #${id} (not in current directory)` });
      }
      for (const actor of choices) {
        const checkbox = el(documentNode, "input");
        checkbox.type = "checkbox";
        checkbox.value = String(actor.id);
        checkbox.checked = selectedActors.has(Number(actor.id));
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) selectedActors.add(Number(actor.id));
          else selectedActors.delete(Number(actor.id));
        });
        actorChoices.appendChild(labelledControl(documentNode, actor.name || `Actor #${actor.id}`, checkbox));
      }
      if (!choices.length) actorChoices.textContent = "No actors are available.";
      loaded = true;
    } catch (error) {
      actorChoices.replaceChildren(el(documentNode, "p", "error",
        presentSessionControlFailure(error, "People and actors could not be loaded.")));
      const retry = el(documentNode, "button", "item-button", "Try again");
      retry.type = "button";
      retry.addEventListener("click", loadActors);
      actorChoices.appendChild(retry);
    } finally { loading = false; update(); }
  };
  mode.addEventListener("change", () => {
    update();
    if (mode.value === "actors") loadActors();
  });
  save.addEventListener("click", async () => {
    if (save.disabled) return;
    const policy = { ...current, mode: mode.value };
    if (mode.value === "actors") {
      if (!selectedActors.size || [...selectedActors].some((id) => !Number.isInteger(id) || id <= 0)) {
        status.textContent = "Select at least one person or actor.";
        return;
      }
      policy.actor_ids = [...selectedActors];
    }
    if (mode.value === "project_role") {
      if (!projects.some((entry) => String(entry.id) === project.value) || !role.value.trim()) {
        status.textContent = "Choose an available project and enter its required role.";
        return;
      }
      policy.project_id = Number(project.value);
      policy.role = role.value.trim();
    }
    busy = true;
    update();
    status.textContent = "Saving access…";
    try {
      const response = await callFunction(context.client, "machine.settings.set", {
        machine_id: result.machine.machine_id, path: "use", value: policy,
      });
      if (response.status !== 200 || !response.envelope?.success) throw response;
      if (context.isMounted()) reload();
    } catch (error) {
      status.textContent = presentSessionControlFailure(error, "Machine access could not be saved.")
        + " Your choices are kept. Try again.";
    } finally { busy = false; update(); }
  });
  update();
  if (mode.value === "actors") loadActors();
  return card;
}
