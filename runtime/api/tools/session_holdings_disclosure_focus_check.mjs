#!/usr/bin/env node
// Prove in a real browser that holdings disclosure expansion survives a
// live roster refresh, that focus returns only when the replaced button
// still owned it, and that focus moved elsewhere is not stolen.

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
const HARNESS_ROUTE = "/session-holdings-disclosure-focus.html";
const CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};

const HARNESS_HTML = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body>
  <div id="roster"></div>
  <button id="elsewhere" type="button">elsewhere</button>
  <script type="module">
    import { sessionCard } from "/universe_views_sessions.js";
    import { renderSessionRows } from "/universe_sessions_history_loader.js";
    const holdings = {
      current: Array.from({ length: 9 }, (_, i) => ({
        holding_kind: "work_claim",
        target_kind: "item",
        target: "YOK-" + (300 + i),
        item_ref: "YOK-" + (300 + i),
        item_project_id: 1,
        item_project_sequence: 300 + i,
      })),
      previous: [],
      previous_remainder: 0,
    };
    const row = {
      session_id: "holdings-disclose-browser",
      liveness: "active",
      mode: "dash",
      executor: "codex",
      activity_at: "2026-08-28T12:00:00Z",
      claims: [],
      holdings,
      messageability: { messageable: false },
    };
    const host = document.getElementById("roster");
    window.__paint = () => {
      renderSessionRows(document, host, [row], () => sessionCard(
        document, row, () => {}, [{ id: 1, slug: "yoke" }],
      ));
    };
    window.__paint();
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

function snapshot() {
  const more = document.querySelector(".session-holdings-more");
  return {
    expanded: more?.getAttribute("aria-expanded") || "",
    focused: document.activeElement === more,
    elsewhere: document.activeElement?.id === "elsewhere",
    restHidden: document.querySelector(".session-holdings-rest")?.hidden === true,
  };
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
    await page.waitForFunction(() => typeof window.__paint === "function");
    await page.click(".session-holdings-more");
    const afterClick = await page.evaluate(snapshot);
    await page.evaluate(() => window.__paint());
    const afterOwnedRefresh = await page.evaluate(snapshot);
    await page.click("#elsewhere");
    await page.evaluate(() => window.__paint());
    const afterMovedRefresh = await page.evaluate(snapshot);
    const failures = [];
    if (afterClick.expanded !== "true" || afterClick.restHidden) {
      failures.push(`click did not expand: ${JSON.stringify(afterClick)}`);
    }
    if (afterOwnedRefresh.expanded !== "true" || !afterOwnedRefresh.focused) {
      failures.push(
        `owned-focus refresh lost expansion or focus: ${JSON.stringify(afterOwnedRefresh)}`,
      );
    }
    if (afterMovedRefresh.expanded !== "true" || !afterMovedRefresh.elsewhere) {
      failures.push(
        `moved-focus refresh stole focus or collapsed: ${JSON.stringify(afterMovedRefresh)}`,
      );
    }
    if (failures.length) {
      console.error("FAIL holdings disclosure focus across refresh");
      for (const failure of failures) console.error(`  - ${failure}`);
      return 1;
    }
    console.log(
      "PASS expansion and focus survive refresh; focus moved elsewhere is not stolen",
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
