import { el, renderError, section } from "./universe_view_support.js";
import {
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";

function editor(documentNode, setting) {
  let control;
  if (setting.value_type === "bool") {
    control = el(documentNode, "select", "session-control-input");
    for (const value of ["true", "false"]) {
      const option = el(documentNode, "option", null, value);
      option.value = value;
      control.appendChild(option);
    }
    control.value = String(Boolean(setting.value));
  } else {
    control = el(documentNode, "input", "session-control-input");
    control.type = "number";
    if (setting.minimum !== null && setting.minimum !== undefined) {
      control.setAttribute("min", String(setting.minimum));
    }
    control.value = String(setting.value);
  }
  control.setAttribute("data-path", setting.path);
  return control;
}

function parsedValue(setting, control) {
  return setting.value_type === "bool"
    ? control.value === "true"
    : Number(control.value);
}

export function renderOrganizationFleet(context, main) {
  const documentNode = context.document;
  const panel = section(documentNode, "Fleet policy");
  const body = panel.children[1];
  body.textContent = "Loading organization fleet policy…";
  main.appendChild(panel);
  const load = async () => {
    try {
      const result = await sessionControlCall(
        context, "organizations.settings.catalog", {},
      );
      if (!context.isMounted()) return;
      body.replaceChildren();
      const form = el(documentNode, "div", "organization-fleet-settings");
      const controls = new Map();
      for (const setting of result.settings || []) {
        const field = el(documentNode, "label", "organization-fleet-setting");
        const title = el(documentNode, "span", "organization-fleet-path", setting.path);
        const meaning = el(documentNode, "span", "organization-fleet-meaning", setting.meaning);
        const control = editor(documentNode, setting);
        controls.set(setting.path, { setting, control });
        field.appendChild(title);
        field.appendChild(meaning);
        field.appendChild(control);
        if (setting.defaulted) {
          field.appendChild(el(documentNode, "span", "session-setting-default", "using default"));
        }
        form.appendChild(field);
      }
      const status = statusRegion(documentNode);
      const save = el(documentNode, "button", "item-button", "Save fleet policy");
      save.type = "button";
      save.addEventListener("click", async () => {
        const assignments = {};
        for (const [path, entry] of controls) {
          const value = parsedValue(entry.setting, entry.control);
          if (value !== entry.setting.value) assignments[path] = value;
        }
        status.hidden = false;
        if (!Object.keys(assignments).length) {
          status.textContent = "Fleet policy is unchanged.";
          return;
        }
        save.disabled = true;
        status.textContent = "Saving organization fleet policy…";
        try {
          const saved = await sessionControlCall(
            context, "organizations.settings.merge", { assignments },
          );
          status.textContent = `Saved ${saved.changed_paths.length} setting(s).`;
          await load();
        } catch (error) {
          status.textContent = String(error.message || error);
          save.disabled = false;
        }
      });
      body.appendChild(form);
      body.appendChild(status);
      body.appendChild(save);
    } catch (error) {
      body.replaceChildren();
      renderError(body, error);
    }
  };
  load();
}
