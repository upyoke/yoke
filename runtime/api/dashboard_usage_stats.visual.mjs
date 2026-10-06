// Render actual dashboard primitives/styles with fixture data, no control-plane universe.
// Usage: node dashboard_usage_stats.visual.mjs OUTPUT_DIR
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";

const [output] = process.argv.slice(2);
assert(output, "Name the output directory.");
// Read the installed browser-control dependency; outputs remain caller-owned.
const runtime = path.join(os.homedir(), ".yoke", "browser-runtime", "package.json");
const { chromium } = createRequire(runtime)("playwright");
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(os.homedir(), ".yoke", "playwright-cache", "yoke");
const staticRoot = fileURLToPath(new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url));
const index = await readFile(path.join(staticRoot, "index.html"), "utf8");
const styles = [...index.matchAll(/href="\/assets\/([^"]+\.css)"/g)].map(m => m[1]);
const html = `<!doctype html><html><head>
${styles.map(name => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
</head><body><div class="universe-app-root"><header>Dashboard layout proof</header>
<div class="shell"><nav class="sidenav">Fixture</nav><div class="workbench-body">
<main class="content"><section id="sessions"></section><section class="machines-grid" id="machines"></section></main>
</div><footer class="app-footer">Candidate styles; fixture data; no control-plane universe</footer></div></div>
<script type="module">
import { renderSessionRows } from "/assets/universe_sessions_history_loader.js";
import { appendMachineUsage } from "/assets/universe_machines_usage.js";
import { summarizeSessionUsage } from "/assets/session_usage_display.js";
import { mountBuildUpdate } from "/assets/universe_build_update.js";
const rows = [{machine_id:"fixture",usage_tokens:123456,usage_status:"complete",usage_cost_usd:12.34,usage_cost_status:"complete"}];
renderSessionRows(document,document.querySelector("#sessions"),[],()=>{},false,"",0,{summary:summarizeSessionUsage(rows)});
for(let i=0;i<3;i++){
 const card=document.createElement("div");card.className="machine-card";
 appendMachineUsage(document,card,{machine_id:"fixture"},rows);document.querySelector("#machines").append(card);
}
const browser=Object.create(window);
browser.fetch=async()=>new Response("new");
browser.addEventListener=window.addEventListener.bind(window);
browser.removeEventListener=window.removeEventListener.bind(window);
browser.setInterval=window.setInterval.bind(window);browser.clearInterval=window.clearInterval.bind(window);
browser.setTimeout=window.setTimeout.bind(window);browser.clearTimeout=window.clearTimeout.bind(window);
mountBuildUpdate(document.querySelector("main"),browser,{runtimeIdentity:{build:"old"}},"/orgs/fixture");
window.proofReady=true;
</script></body></html>`;
const server = createServer(async(req,res)=>{
 try {
  const name = new URL(req.url,"http://fixture").pathname;
  if(name === "/") { res.setHeader("Content-Type","text/html");res.end(html);return; }
  const asset=path.basename(name);
  res.setHeader("Content-Type",asset.endsWith(".css")?"text/css":"text/javascript");
  res.end(await readFile(path.join(staticRoot,asset)));
 } catch {res.statusCode=404;res.end();}
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const measurements={};
try {
 for(const width of [1280,390]){
  const page=await browser.newPage({viewport:{width,height:900}});
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(()=>window.proofReady);
  await page.locator(".build-update-banner:not([hidden])").waitFor();
  const data=await page.evaluate(()=>{
   const heights=selector=>[...document.querySelectorAll(selector)].map(n=>n.getBoundingClientRect().height);
   return {sessions:heights(".sessions-stats > div"),machines:[...document.querySelectorAll(".machine-usage")].map(n=>heightsWithin(n)),
    costLabels:[...document.querySelectorAll('[data-usage-fact="cost"] .usage-stat-unit')].map(n=>({text:n.textContent,height:n.getBoundingClientRect().height})),
    overflow:document.documentElement.scrollWidth>innerWidth};
   function heightsWithin(n){return [...n.children].map(c=>c.getBoundingClientRect().height);}
  });
  if(width===1280){
   assert(Math.max(...data.sessions)-Math.min(...data.sessions)<1,JSON.stringify(data));
   for(const row of data.machines)assert(Math.max(...row)-Math.min(...row)<1,JSON.stringify(data));
  }
  assert(data.costLabels.length===4 && data.costLabels.every(n=>n.text==="24h cost"),JSON.stringify(data));
  assert(!data.overflow,JSON.stringify(data));
  measurements[width]=data;
  await page.screenshot({path:path.join(output,`dashboard-stats-${width}.png`),fullPage:true});
  await page.close();
 }
 await writeFile(path.join(output,"measurements.json"),JSON.stringify(measurements,null,2));
 console.log(JSON.stringify(measurements));
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
