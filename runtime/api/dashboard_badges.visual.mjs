// Candidate dashboard renderers with populated fixtures; no universe reads.
// node dashboard_badges.visual.mjs PLAYWRIGHT_MODULE OUTPUT_DIR [STATIC_ROOT]
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
const [modulePath, output, sourceRoot] = process.argv.slice(2);
assert(modulePath && output, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(modulePath);
const root = sourceRoot || fileURLToPath(new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url));
const styles = [...(await readFile(path.join(root, "index.html"), "utf8"))
  .matchAll(/href="(?:\.\/|\/)assets\/([^\"]+\.css)"/g)].map((m) => m[1]);
assert(styles.length, "Source index must declare its stylesheet roster.");
const rows = ["wrapping-row", "activation-head", "machine-detail-fact", "machine-harness-row",
  "machine-head", "page-head", "panel-header", "item-roster-toolbar", "qa-method-foot",
  "qa-plan-outcome", "review-foot", "review-head", "run-card h2", "runtime-identity-help-row",
  "secondary-card-header", "event-header", "session-holding-history", "session-message-header",
  "session-top", "strategy-doc-metadata", "strategy-spark-label", "test-machine-head",
  "workflow-dialog-footer", "workflow-panel-meta"];
const flow = "production-release-with-consumer-verification-and-item-quality-assurance";
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">${styles.map((s) => `<link rel="stylesheet" href="/assets/${s}">`).join("")}
<style>body{margin:0;padding:0}.proof{margin:0 0 20px;min-width:0}.content{max-width:100%}
#rows{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.sample{border:1px solid #aaa;padding:10px;min-width:0}.sample label,footer{font:12px sans-serif}
.sample-row{display:flex;gap:10px;margin:8px 0}.sample-row>.long{flex-basis:100%}</style></head>
<body><main class="universe-app-root"><div class="content">
<h1>Populated dashboard layout evidence</h1><div id="session" class="proof"></div>
<div id="launches" class="proof"></div><div id="projects" class="proof"></div><div id="strategy" class="proof"></div><div id="actors" class="proof"></div>
<div id="workflows" class="proof"></div><div id="card" class="proof"></div>
<div id="item" class="proof"></div><div id="actions" class="proof"></div><div id="rows"></div>
<footer>Candidate assets · populated deterministic fixtures · no control-plane universe</footer>
</div></main><script type="module">
import { createWorkbenchChrome } from "/assets/universe_app_chrome.js";
import { sessionRosterFilters } from "/assets/universe_session_roster_filters.js";
import { launchFilters } from "/assets/universe_session_launch_filters.js";
import { renderProjectsView } from "/assets/universe_views_projects.js";
import { sessionCard } from "/assets/universe_views_sessions.js";
import { strategyDocumentCard } from "/assets/universe_strategy_cards.js";
import { renderActorsView } from "/assets/universe_views_actors.js";
import { renderMechanics } from "/assets/workflow_view_mechanics.js";
import { appendItemDelivery } from "/assets/universe_item_deployment.js";
import { itemDeliveryPanel } from "/assets/item_view_delivery.js";
const project={id:1,name:"Demo",public_item_prefix:"DEMO"};
document.querySelector("#session").append(sessionCard(document,{session_id:"fixture-session",
 executor:"codex",executor_surface:"codex-cli",liveness:"active",mode:"dash",model:"gpt-6.1-sol",
 actor_label:"Deployment reviewer",execution_lane:"ALTMAN",claimed_items:[]},()=>{},[project]));
document.querySelector("#strategy").append(strategyDocumentCard(document,{slug:"CURRENT-PLAN",
 state:"ACTIVE",project_id:1,updated_at:"2026-10-05T12:00:00Z",summary:"Ship verified dashboard corrections."},project));
const actor={id:1,name:"Deployment reviewer",kind:"human",status:"active",roles:{org:[{role:"admin"}]},
 tokens:[{name:"release_automation_credential_inventory_for_production_deployment",token_id:7,last_used_at:"2026-10-05T12:00:00Z",
 machine_id:"fixture-machine",machine_name:"Production deployment workstation"}]};
const context={document,isMounted:()=>true,capabilities:{data:{portability:{mode:"hosted"}}},
 client:{call:async(request)=>({status:200,envelope:{success:true,result:request.function==="actors.roster"
 ? {rows:[actor],current_actor_id:1,can_manage_actors:false}:{rows:[]}}})}};
const launches=launchFilters(document,()=>{});launches.offer([{state:"succeeded",selected_surface:"codex-cli",assigned_machine_id:"fixture-machine"}]);
document.querySelector("#launches").append(launches.host);
renderProjectsView(context,document.querySelector("#projects"));
await renderActorsView(context,document.querySelector("#actors"));
document.querySelector("#workflows").append(renderMechanics(document,{id:"dash",name:"Dash",
 definition:{policies:{qa:"optional_item_attachment"},skill_bindings:[{skill_id:"dash"}]}},{editTesting:()=>{}}));
appendItemDelivery(document,document.querySelector("#card"),{id:1,completion_flow:${JSON.stringify(flow)}},new Map());
document.querySelector("#item").append(itemDeliveryPanel(context,{public_ref:"DEMO-1",project,
 completion_flow:${JSON.stringify(flow)},completion_flow_source:"item"}));
for(const name of ${JSON.stringify(rows)}){
 const section=document.createElement("section");section.className="sample";
 section.innerHTML='<label>'+name+'</label>';
 for(const wrapped of [false,true]){
  const host=document.createElement("div");if(name==="run-card h2")host.className="run-card";
  const row=document.createElement(name==="run-card h2"?"h2":"div");
  row.className=(name==="run-card h2"?"":name)+" sample-row";row.dataset.wrapped=wrapped;
  row.innerHTML='<span class="pill">ACTIVE</span><span></span>';
  row.lastChild.textContent=wrapped?"Wrapped context begins at the left edge of its row.":"Ready";
  if(wrapped)row.lastChild.className="long";
  host.append(row);section.append(host);
 }
 document.querySelector("#rows").append(section);
}
const filters=sessionRosterFilters(document,()=>{});
for(const label of ["Message all","Reclaim stale","Load more"]){const b=document.createElement("button");b.className="item-button session-filter-action";b.textContent=label;filters.actions.append(b);}
document.querySelector("#session").prepend(filters.host);
for(const actionClass of ["head-actions","review-actions","test-machine-actions","workflow-dialog-actions","session-filter-actions"]){
for(const text of ["Review", "Review the production deployment candidate and its complete evidence"]){
 const row=document.createElement("div");row.className="page-head proof-heading";
 row.innerHTML='<div class="h"><h1 class="title">Heading</h1></div><div class="head-actions"><button class="item-button"></button></div>';
 row.lastChild.className=actionClass;row.lastChild.style.display="flex";row.lastChild.firstChild.textContent=text;document.querySelector("#actions").append(row);
}
}
const contents=document.querySelector(".content");
const chrome=createWorkbenchChrome({client:context.client,context,documentNode:document,
 mountedSlotNodes:[],options:{currentActor:{kind:"human",label:"Ben Bauman"},capabilities:context.capabilities},
 resolvedSections:{},resolvedSlots:{},slots:{}});
chrome.main.replaceChildren(...contents.childNodes);
document.querySelector(".universe-app-root").replaceChildren(chrome.header,chrome.shell);
chrome.orgContext.textContent="upyoke";
chrome.setScopeVisible(true);chrome.scopeHost.innerHTML='<div class="scope-bar"><button class="scope-chip on">Demo</button></div>';
window.proofReady=true;
</script></body></html>`;
const server=createServer(async(req,res)=>{try{
 if(req.url==="/"){res.setHeader("Content-Type","text/html");res.end(html);return;}
 const name=new URL(req.url,"http://localhost").pathname.slice(8);
 assert(!name.includes("/")&&!name.includes(".."));
 res.setHeader("Content-Type",name.endsWith(".js")?"text/javascript":"text/css");
 res.end(await readFile(path.join(root,name)));
}catch(error){res.statusCode=500;res.end(String(error));}});
await new Promise((resolve)=>server.listen(0,"127.0.0.1",resolve));
await mkdir(output,{recursive:true});const browser=await chromium.launch({headless:true});
const freshPage=async(width)=>{
 const page=await browser.newPage({viewport:{width,height:1000},hasTouch:width<1280,isMobile:width<1280});
 const errors=[];page.on("pageerror",(e)=>errors.push(String(e)));
 await page.goto(`http://127.0.0.1:${server.address().port}/`);
 await page.waitForFunction(()=>window.proofReady && document.querySelector(".actors-key")
   && document.querySelector(".item-delivery-flow a") && document.querySelector(".session-harness")
   && document.querySelector(".strategy-doc-state")?.textContent==="ACTIVE");
 assert.deepEqual(errors,[]);
 assert.equal(await page.evaluate(()=>matchMedia("(hover: none)").matches),width<1280);
 return page;
};
try{
 for(const width of [1280,390,375,320]){
  const page=await freshPage(width);
  const data=await page.evaluate(()=>{
   const r=(n)=>n.getBoundingClientRect();
   const rows=[...document.querySelectorAll(".sample-row")].map((n)=>({
    name:n.closest(".sample").firstChild.textContent,grow:getComputedStyle(n.firstChild).flexGrow,
    wrapped:n.dataset.wrapped==="true",offset:r(n.lastChild).left-r(n.firstChild).left}));
   const heading=[...document.querySelectorAll(".proof-heading")].map((n)=>({
    wrapped:r(n.lastChild).top>=r(n.firstChild).bottom-1,left:r(n.lastChild).left-r(n).left,
    right:r(n).right-r(n.lastChild).right}));
   const testing=[...document.querySelectorAll(".workflow-detail-row")].find((n)=>n.textContent.startsWith("Testing"));
   const key=document.querySelector(".actors-key");const cell=key.parentElement;
   const badge=document.querySelector(".session-harness");const state=document.querySelector(".strategy-doc-state");
   const card=document.querySelector("#card .item-delivery-head");const label=card.firstChild;const flow=card.lastChild;
   return {rows,heading,filterHeights:[...document.querySelectorAll(".session-roster-filter,.session-filter-action")].map((n)=>r(n).height),badgeWidth:r(badge).width,stateWidth:r(state).width,
    key:{tableWidth:r(cell.closest("table")).width,wrapWidth:r(cell.closest(".table-wrap")).width,text:key.textContent,whiteSpace:getComputedStyle(cell).whiteSpace,scroll:key.scrollWidth,width:key.clientWidth},
    testing:{copyRight:r(testing.firstChild).right,actionLeft:r(testing.children[1]).left,
      actionTop:r(testing.children[1]).top,copyBottom:r(testing.firstChild).bottom},
    card:{margin:getComputedStyle(flow).marginTop,left:r(flow).left-r(label).left,top:r(flow).top-r(label).top},
    item:{display:getComputedStyle(document.querySelector("#item .item-delivery-flow")).display,
      margin:getComputedStyle(document.querySelector("#item .item-delivery-flow")).marginTop}};
  });
  await writeFile(path.join(output,`measurements-${width}.json`),JSON.stringify(data,null,2));
  if(!sourceRoot){
   assert(data.filterHeights.every((h)=>h===34),"Sessions control heights must all be 34px");
   assert(data.badgeWidth<40);assert(data.stateWidth<90);
   for(const row of data.rows){assert.equal(row.grow,"0",row.name);if(row.wrapped)assert(Math.abs(row.offset)<1,row.name);}
   for(const row of data.heading)assert(Math.abs(row.wrapped?row.left:row.right)<1,"Heading actions alignment");
   assert.equal(data.key.whiteSpace,"normal");assert(data.key.scroll<=data.key.width+1);
   assert(data.key.tableWidth<=data.key.wrapWidth+1,"Actor inventory exceeds visible table");
   assert(data.testing.actionLeft>=data.testing.copyRight-1 || data.testing.actionTop>=data.testing.copyBottom-1,"Testing overlap");
   assert.equal(data.card.margin,"0px");if(data.card.top>1)assert(Math.abs(data.card.left)<1);
   assert.deepEqual(data.item,{display:"flex",margin:"10px"});
  }
  const header=await page.locator(".topbar").evaluate((n)=>{
   const style=getComputedStyle(n);return {width:n.getBoundingClientRect().width,gap:style.columnGap,
    hoverNone:matchMedia("(hover: none)").matches, actorPadding:getComputedStyle(n.querySelector(".actor-chip")).padding, padding:[style.paddingLeft,style.paddingRight],children:[...n.children].map((b)=>({class:b.className,width:b.getBoundingClientRect().width,display:getComputedStyle(b).display})),boxes:[...n.querySelectorAll(".navigation-toggle,.header-search-button,.header-context-control")]
     .map((b)=>({class:b.className,text:b.textContent,top:b.getBoundingClientRect().top,
       width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))};
  });
  await writeFile(path.join(output,`header-${width}.json`),JSON.stringify(header,null,2));
  if(!sourceRoot && width===390){
   assert(header.hoverNone,"Phone proof must exercise hover:none");
   const first=header.boxes.filter((b)=>!b.class.includes("project"));
   assert(Math.max(...first.map((b)=>b.top)) < Math.min(...first.map((b)=>b.top+b.height)),"Menu, search, Universe and Actor must share row at 390px");
  }
  if(!sourceRoot && width===390){
   const controls=await page.locator(".header-context-control").evaluateAll((nodes)=>nodes.map((n)=>n.getBoundingClientRect().height));
   assert.equal(new Set(controls).size,1,"Header context heights differ");
   assert(await page.locator(".scope-chip").evaluate((n)=>n.getBoundingClientRect().height)<=22);
  }
  await page.screenshot({path:path.join(output,`populated-${width}.png`),fullPage:true});
  await page.close();
  const headerPage=await freshPage(width);
  await headerPage.locator(".topbar").screenshot({path:path.join(output,`header-${width}.png`)});
  await headerPage.close();
  if(width===390){
   const menuPage=await freshPage(width);
   await menuPage.locator(".navigation-toggle").tap();
   await menuPage.waitForFunction(()=>document.querySelector(".shell").classList.contains("side-open") && document.querySelector("#universe-navigation").getBoundingClientRect().left===0);
   if(!sourceRoot)assert.equal(await menuPage.locator(".navigation-close").count(),0);
   if(!sourceRoot){
   await menuPage.locator(".navigation-scrim").tap({position:{x:380,y:600},force:true});
   await menuPage.waitForFunction(()=>!document.querySelector(".shell").classList.contains("side-open"));
   await menuPage.locator(".navigation-toggle").tap();
   await menuPage.waitForFunction(()=>document.querySelector("#universe-navigation").getBoundingClientRect().left===0);
   }
   await menuPage.screenshot({path:path.join(output,"menu-390.png"),fullPage:false});
   await menuPage.close();
  }
  console.log(`${sourceRoot?"before":"after"} ${width}px: populated cards, Actors, Workflows, ${rows.length} row classes, both Delivery surfaces`);
 }
}finally{await browser.close();await new Promise((resolve)=>server.close(resolve));}
