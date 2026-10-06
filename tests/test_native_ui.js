// Exercise the generated page mounts with DOM stand-ins (not a visual browser test).
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..');let mountLinks;
class AppPlugin{setRootPage(){return this}}
class Element{
 constructor(){this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.dataset={};this.classList={add(){},remove(){},toggle(){}}}
 querySelectorAll(){return []}
 set innerHTML(v){this.html=v}
 get innerHTML(){return this.html}
}
class Shadow{
 set innerHTML(v){this.html=v;this.elements={};for(const m of v.matchAll(/<([a-z0-9]+)[^>]*\bid="([^"]+)"[^>]*>/g)){const el=new Element();el.tag=m[1];el.value=(m[0].match(/value="([^"]*)"/)||[])[1]||'';if(m[1]==='select'){const after=v.slice(m.index+m[0].length);el.value=(after.match(/<option value="([^"]*)"/)||after.match(/<option>([^<]*)/ )||[])[1]||''}el.reset=()=>{};el.showModal=()=>{};el.close=()=>{};this.elements[m[2]]=el}}
 getElementById(id){assert(this.elements[id],`Unknown element ${id}`);return this.elements[id]}
 querySelectorAll(selector){if(selector==='form input,form select')return Object.values(this.elements).filter(e=>['input','select'].includes(e.tag));return []}
 addEventListener(){}
}
const System={register(deps,factory){const r=factory((k,v)=>{if(k==='_mountLinks')mountLinks=v});r.setters[0]({});r.setters[1]({AppPlugin});r.setters[2]({});r.execute()}};
let bundle=fs.readFileSync(path.join(root,'config/grafana/plugins/dunker-integracoes-app/module.js'),'utf8').replace("exports('plugin',", "exports('_mountLinks',mountLinks);exports('plugin',");
vm.runInNewContext(bundle,{System,console,MutationObserver:class{observe(){}disconnect(){}},setInterval,clearInterval});
(async()=>{
 for(const area of ['links','snmp'])for(const canEdit of [false,true]){
  const shadow=new Shadow(),calls=[],host={attachShadow:()=>shadow,remove(){}};
  const dispose=mountLinks(host,async p=>{calls.push(p);return []},area,canEdit);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[area==='links'?'/api/monitors':'/api/devices']);
  if(!canEdit){assert(shadow.getElementById(area==='links'?'new':'deviceNew').hidden);assert(shadow.getElementById(area==='links'?'save':'deviceSave').hidden)}
  else assert(!shadow.getElementById(area==='links'?'new':'deviceNew').hidden);
  dispose();
 }
 console.log('Native UI mounts: links/SNMP, separate reads, read-only and editing states OK; no visual browser validation.');
})().catch(e=>{console.error(e);process.exitCode=1});
