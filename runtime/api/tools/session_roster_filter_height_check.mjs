#!/usr/bin/env node
// Prove in a real browser that the Sessions roster filter controls line up.
//
// Search plus the State, Harness, and Machine selects sit in compact bordered
// wrappers. This tool renders the real module under the product stylesheet
// cascade in Chromium and proves the four wrappers align.
//
// The same rule also sizes the message textarea and the session-control
// panel inputs, so the tool renders those too and refuses when the filter
// fix has flattened the textarea or shrunk the panel controls.
//
// Chromium and Playwright come from the machine's Yoke browser runtime
// (`yoke qa browser status`), never from a project dependency.

import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const STATIC_DIR = join(
  REPO_ROOT, "packages", "yoke-core", "src", "yoke_core", "ui", "static",
);
const HARNESS_ROUTE = "/session-roster-filter-heights.html";
const CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
};
const MESSAGE_BODY_MIN_HEIGHT_PX = 130;
const CONTROL_MIN_HEIGHT_PX = 34;

// The page mirrors the Sessions view's real ancestry (.universe-app-root >
// .sessions-view) so the cascade the filters meet is the product's, and
// mounts the shared-selector consumers the fix must leave alone.
const HARNESS_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="/theme.css">
  <link rel="stylesheet" href="/shell.css">
  <link rel="stylesheet" href="/app.css">
</head>
<body class="local-universe-page">
  <div class="universe-app-root">
    <div class="sessions-view" id="filters"></div>
    <div class="session-control-panel" id="panel">
      <label class="session-control-field"><span>Item</span>
        <input class="session-control-input" data-probe="panel-input"></label>
      <label class="session-control-field"><span>Surface</span>
        <select class="session-control-input" data-probe="panel-select">
          <option>claude-cli</option></select></label>
      <label class="session-control-field"><span>Message</span>
        <textarea class="session-control-input session-message-body"
          data-probe="message-body"></textarea></label>
    </div>
  </div>
  <script type="module">
    import { sessionRosterFilters } from "/universe_session_roster_filters.js";
    const filters = sessionRosterFilters(document, () => {});
    document.getElementById("filters").appendChild(filters.host);
    window.__filtersMounted = true;
  </script>
</body>
</html>
`;

function browserRuntimeDir() {
  const home = (process.env.YOKE_MACHINE_HOME || "").trim();
  return join(home || join(homedir(), ".yoke"), "browser-runtime");
}

function loadPlaywright() {
  const runtimeDir = browserRuntimeDir();
  try {
    return createRequire(join(runtimeDir, "package.json"))("playwright");
  } catch (error) {
    throw new Error(
      `Playwright is not available from the Yoke browser runtime at ${runtimeDir}`
      + ` (${error.message}). Run \`yoke qa browser setup\` to materialize the`
      + " runtime and its Chromium, then re-run this check.",
    );
  }
}

async function serveStatic(request, response) {
  const pathname = new URL(request.url, "http://127.0.0.1").pathname;
  if (pathname === HARNESS_ROUTE) {
    response.writeHead(200, { "content-type": CONTENT_TYPES[".html"] });
    response.end(HARNESS_HTML);
    return;
  }
  const target = normalize(join(STATIC_DIR, pathname));
  if (!target.startsWith(STATIC_DIR)) {
    response.writeHead(403).end();
    return;
  }
  try {
    const body = await readFile(target);
    response.writeHead(200, {
      "content-type": CONTENT_TYPES[extname(target)] || "application/octet-stream",
    });
    response.end(body);
  } catch {
    response.writeHead(404).end(`missing static asset: ${pathname}`);
  }
}

function listen(server) {
  return new Promise((ready, failed) => {
    server.once("error", failed);
    server.listen(0, "127.0.0.1", () => ready(server.address().port));
  });
}

// Runs inside the page: one row per control, measured by layout.
function measureControls() {
  const rows = [];
  for (const wrapper of document.querySelectorAll(".session-roster-filter")) {
    const control = wrapper.querySelector("input, select");
    const style = getComputedStyle(control);
    rows.push({
      group: "filter",
      label: control.getAttribute("aria-label")
        || wrapper.querySelector(".session-filter-label").textContent,
      tag: control.tagName.toLowerCase(),
      height: wrapper.getBoundingClientRect().height,
      control_height: control.getBoundingClientRect().height,
      css_height: style.height,
      css_min_height: style.minHeight,
    });
  }
  for (const control of document.querySelectorAll("[data-probe]")) {
    const style = getComputedStyle(control);
    rows.push({
      group: "shared",
      label: control.dataset.probe,
      tag: control.tagName.toLowerCase(),
      height: control.getBoundingClientRect().height,
      css_height: style.height,
      css_min_height: style.minHeight,
      css_resize: style.resize,
    });
  }
  return rows;
}

function judge(rows) {
  const failures = [];
  const filters = rows.filter((row) => row.group === "filter");
  const expectedLabels = ["Search", "State", "Harness", "Machine"];
  const labels = filters.map((row) => row.label);
  if (JSON.stringify(labels) !== JSON.stringify(expectedLabels)) {
    failures.push(
      `expected filter controls ${expectedLabels.join(", ")}; rendered ${labels.join(", ") || "none"}`,
    );
  }
  const heights = new Set(filters.map((row) => row.height));
  if (heights.size !== 1) {
    failures.push(
      "filter wrapper heights differ: "
      + filters.map((row) => `${row.label} <${row.tag}> ${row.height}px`).join(", "),
    );
  }
  const short = filters.filter((row) => row.height < CONTROL_MIN_HEIGHT_PX);
  if (short.length) {
    failures.push(
      `filter wrappers below ${CONTROL_MIN_HEIGHT_PX}px: ${short.map((row) => row.label).join(", ")}`,
    );
  }
  const tags = filters.map((row) => row.tag);
  if (JSON.stringify(tags) !== JSON.stringify(["input", "select", "select", "select"])) {
    failures.push(`expected search input then three selects; rendered ${tags.join(", ")}`);
  }
  const shared = Object.fromEntries(
    rows.filter((row) => row.group === "shared").map((row) => [row.label, row]),
  );
  const body = shared["message-body"];
  if (!body || body.height < MESSAGE_BODY_MIN_HEIGHT_PX || body.css_resize !== "vertical") {
    failures.push(
      `message textarea must stay at least ${MESSAGE_BODY_MIN_HEIGHT_PX}px tall and`
      + ` vertically resizable; measured ${body ? `${body.height}px resize=${body.css_resize}` : "no textarea"}`,
    );
  }
  for (const label of ["panel-input", "panel-select"]) {
    const row = shared[label];
    if (!row || row.height < CONTROL_MIN_HEIGHT_PX) {
      failures.push(
        `${label} must keep the shared ${CONTROL_MIN_HEIGHT_PX}px minimum;`
        + ` measured ${row ? `${row.height}px` : "no control"}`,
      );
    }
  }
  return failures;
}

async function main() {
  const { chromium } = loadPlaywright();
  const server = createServer((request, response) => {
    serveStatic(request, response).catch((error) => {
      response.writeHead(500).end(String(error));
    });
  });
  const port = await listen(server);
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    page.on("pageerror", (error) => {
      throw new Error(`harness page error: ${error.message}`);
    });
    await page.goto(`http://127.0.0.1:${port}${HARNESS_ROUTE}`);
    await page.waitForFunction(() => window.__filtersMounted === true);
    await page.evaluate(() => document.fonts.ready);
    const rows = await page.evaluate(measureControls);
    for (const row of rows) console.log(JSON.stringify(row));
    const failures = judge(rows);
    if (failures.length) {
      console.error("FAIL session roster filter heights");
      for (const failure of failures) console.error(`  - ${failure}`);
      console.error(
        "  fix: universe_session_control.css must align the compact filter"
        + " wrappers without touching shared .session-control-input minimums.",
      );
      return 1;
    }
    console.log(
      `PASS all ${rows.filter((row) => row.group === "filter").length} filter controls`
      + ` align at ${rows[0].height}px; shared controls keep their sizes`,
    );
    return 0;
  } finally {
    await browser.close();
    server.close();
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`ERROR ${error.message}`);
    process.exit(2);
  },
);
