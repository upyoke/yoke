import assert from "node:assert/strict";
import path from "node:path";
import { writeFile } from "node:fs/promises";

// Real renderers extend the populated dashboard fixture; callbacks never mutate a universe.
export const alignmentFixture = `
import { strategyWriteActivity } from "/assets/strategy_view_summary.js";
import { renderQaMethods } from "/assets/qa_view_methods.js";
import { terminalizationDialog } from "/assets/deployment_run_terminalization_dialog.js";
import { waiverDialog } from "/assets/qa_plan_actions.js";
const alignment=document.createElement("section");alignment.id="alignment";alignment.className="proof";
chrome.main.append(alignment);
alignment.append(strategyWriteActivity(document,[{day:new Date().toISOString().slice(0,10),writes:7}]));
const methodHost=document.createElement("div");alignment.append(methodHost);
await renderQaMethods({...context,projects:()=>[project],client:{call:async()=>({status:200,envelope:{success:true,result:{rows:[{
 id:"browser-inspection",name:"Browser inspection",description:"Review populated candidate layouts.",used_by_plan_count:3,
 required_capabilities:[{kind:"browser-control",label:"Browser control",state:"configured",context:{state:"configured"}}]
}]}}})}},methodHost,"all");
const samples=document.createElement("div");samples.id="alignment-samples";alignment.append(samples);
for(const original of [alignment.querySelector(".strategy-spark-label"),alignment.querySelector(".qa-method-foot")]){
 for(const width of [280,120]){
  const host=document.createElement("div");host.className="proof";host.style.width=width+"px";
  const row=original.cloneNode(true);row.classList.add("aligned-value");host.append(row);samples.append(host);
 }
}
for(const name of ["instruction-editor-actions","item-form-actions","workflow-dialog-footer actions-only"]){
 for(const text of ["Save", "Save the production deployment candidate and all reviewed evidence"]){
  const host=document.createElement("section");host.className=name==="item-form-actions"?"proof item-new":"proof";
  const row=document.createElement("div");row.className=name+" aligned-actions";
  row.innerHTML='<button class="item-button">Cancel</button><button class="item-button"></button>';
  row.lastChild.textContent=text;host.append(row);alignment.append(host);
 }
}
window.openProofDialog=(kind)=>{
 const overlay=kind==="terminalization"?terminalizationDialog(context,{id:"fixture-release",status:"executing"},()=>{}):
  waiverDialog(context,{case_key:"populated-layout",last_result:{requirement_id:1}},()=>{});
 document.querySelector(".universe-app-root").append(overlay);
};
window.secondProofPicker=()=>{
 const focus=document.createElement("div");focus.className="scope-bar";
 focus.innerHTML='<span>Focus</span><button class="scope-chip on">Demo</button>';
 chrome.scopeHost.firstChild.append(focus);
};
`;

const alignmentMeasurements=async(page)=>page.evaluate(()=>{
 const rect=(n)=>n.getBoundingClientRect();
 const rowData=(n)=>{const first=n.firstElementChild,last=n.lastElementChild,style=getComputedStyle(n);
  return {name:n.className,wrapped:rect(last).top>=rect(first).bottom-1,
   left:rect(last).left-rect(first).left,right:rect(n).right-rect(last).right-parseFloat(style.paddingRight)-parseFloat(style.borderRightWidth||0)};};
 return {values:[...document.querySelectorAll(".aligned-value")].map(rowData),
  actions:[...document.querySelectorAll(".aligned-actions")].map((n)=>({...rowData(n),
   groupLeft:rect(n).left-rect(n.parentElement).left,groupRight:rect(n.parentElement).right-rect(n).right})),
  footer:{right:rect(document.querySelector(".app-footer")).right-rect(document.querySelector(".app-footer-links")).right
   -parseFloat(getComputedStyle(document.querySelector(".app-footer")).paddingRight)},
  searchWidth:rect(document.querySelector(".session-filter-search")).width};
});

export async function captureAlignmentProof({freshPage,output,baseline}){
 const measured={};
 for(const width of [1280,390]){
  const page=await freshPage(width);const data=await alignmentMeasurements(page);
  if(!baseline){
   for(const row of data.values)assert(Math.abs(row.wrapped?row.left:row.right)<1,JSON.stringify(row));
   for(const row of data.actions){assert(Math.abs(row.wrapped?row.groupLeft:row.groupRight)<1,JSON.stringify(row));
    if(row.wrapped)assert(Math.abs(row.left)<1,JSON.stringify(row));}
   assert(Math.abs(data.footer.right)<1,"Fitting footer links must reach right edge");
   assert(data.searchWidth<=340,"Sessions search cap must remain340px");
  }
  measured[width]=data;
  await page.locator("#alignment").screenshot({path:path.join(output,`alignment-${width}.png`)});await page.close();
  const footerPage=await freshPage(width);
  await footerPage.locator(".app-footer").screenshot({path:path.join(output,`footer-${width}.png`)});await footerPage.close();
  const identityPage=await freshPage(width);await identityPage.locator(".app-footer-version").click();
  const identity=await identityPage.locator(".runtime-identity-help .runtime-identity-help-row").evaluateAll((nodes)=>nodes.map((n)=>{
   const a=n.firstChild.getBoundingClientRect(),b=n.lastChild.getBoundingClientRect(),r=n.getBoundingClientRect();
   return {wrapped:b.top>=a.bottom-1,left:b.left-a.left,right:r.right-b.right};}));
  if(!baseline)for(const row of identity)assert(Math.abs(row.wrapped?row.left:row.right)<1,JSON.stringify({width,identity}));
  measured[width].identity=identity;
  await identityPage.locator(".runtime-identity-help").screenshot({path:path.join(output,`identity-${width}.png`)});await identityPage.close();
  for(const kind of ["terminalization","waiver"]){
   const dialogPage=await freshPage(width);await dialogPage.evaluate((k)=>window.openProofDialog(k),kind);
   const selector=kind==="terminalization"?".deployment-terminalization-actions":".qa-action-dialog-buttons";
   await dialogPage.locator(selector).waitFor();
   const dialog=await dialogPage.locator(selector).evaluate((n)=>{const a=n.firstChild.getBoundingClientRect(),b=n.lastChild.getBoundingClientRect();
    const r=n.getBoundingClientRect(),host=n.parentElement.getBoundingClientRect(),s=getComputedStyle(n.parentElement);
    return {wrapped:b.top>=a.bottom-1,left:b.left-a.left,groupLeft:r.left-host.left-parseFloat(s.paddingLeft)-parseFloat(s.borderLeftWidth),
     right:host.right-r.right-parseFloat(s.paddingRight)-parseFloat(s.borderRightWidth)};});
   if(!baseline)assert(Math.abs(dialog.wrapped?dialog.groupLeft:dialog.right)<1,JSON.stringify(dialog));
   measured[width][kind]=dialog;
   await dialogPage.screenshot({path:path.join(output,`${kind}-${width}.png`)});await dialogPage.close();
  }
 }
 for(const width of [390,375,320]){
  const page=await freshPage(width);await page.evaluate(()=>window.secondProofPicker());
  const data=await page.locator(".header-project-context").evaluate((n)=>({height:n.getBoundingClientRect().height,
   pickerBottom:n.querySelector(".scope-bar .scope-bar").getBoundingClientRect().bottom,boxBottom:n.getBoundingClientRect().bottom,
   actorHeight:document.querySelector(".header-actor-context").getBoundingClientRect().height}));
  if(!baseline){assert(data.height>data.actorHeight);assert(data.pickerBottom<data.boxBottom,"Second picker clips");}
  measured[`two-pickers-${width}`]=data;
  await page.locator(".topbar").screenshot({path:path.join(output,`header-two-pickers-${width}.png`)});await page.close();
 }
 const page=await freshPage(390);await page.locator(".actor-chip").evaluate((n)=>n.style.fontSize="16px");
 measured.actorInheritedFont=await page.locator(".topbar").evaluate((n)=>[...n.querySelectorAll(".navigation-toggle,.header-search-button,.header-universe-context,.header-actor-context")].map((b)=>({name:b.className,top:b.getBoundingClientRect().top,width:b.getBoundingClientRect().width})));
 if(!baseline)assert(measured.actorInheritedFont[3].top>measured.actorInheritedFont[0].top,"Inherited16px Actor font should exercise the overflow that12.5px fixes");
 await page.locator(".topbar").screenshot({path:path.join(output,"header-actor-inherited-390.png")});await page.close();
 await writeFile(path.join(output,"alignment-measurements.json"),JSON.stringify(measured,null,2));
 console.log("Fitting right / wrapped left alignment, dialogs, filters and two-picker header proof completed.");
}
