// Behavioral UI checks with a small DOM stand-in; no browser/visual validation.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../config/admin/sharepoint-ui.js'),'utf8');
class Element {
 constructor(){this.value='';this.hidden=false;this.disabled=false;this.classList={add(){},toggle(){}};this.elements={};this.textContent=''}
 querySelectorAll(){return []}scrollIntoView(){}reset(){}reportValidity(){return true}
 set innerHTML(v){this.html=v}get innerHTML(){return this.html}
}
class Root extends Element {
 set innerHTML(v){this.html=v;this.nodes={};this.fields={};for(const m of v.matchAll(/<([a-z]+)[^>]*\b(data-el|name)="([^"]+)"[^>]*>/g)){const e=new Element();if(m[1]==='select'){e.value=(v.slice(m.index+m[0].length).match(/<option value="([^"]*)"/)||[])[1]||''}if(m[2]==='data-el')this.nodes[m[3]]=e;else this.fields[m[3]]=e;}if(this.nodes.form){this.fields.namedItem=k=>this.fields[k]||null;this.nodes.form.elements=this.fields;}}
 querySelector(s){return this.nodes[s.match(/data-el="([^"]+)"/)[1]]}
}
const context={setInterval:()=>1,clearInterval(){},console};vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const root=new Root(),sent=[];context.mountSharePoint(root,async(p,o)=>{if(o?.body){sent.push(JSON.parse(o.body));return {}}return []});
 await root.nodes.new.onclick();
 assert(root.html.indexOf('<details class="sp-help" open>')<root.html.indexOf('<form data-el="form">'));
 assert(root.html.includes('Reports.Read.All'));assert(root.html.includes('Sites.Read.All'));assert(root.html.includes('Valor'));
 root.fields.capacity_value.value='1536';root.fields.capacity_unit.value='TB';root.fields.capacity_unit.onchange();assert.equal(root.fields.capacity_value.value,'1.5');
 root.fields.capacity_unit.value='GB';root.fields.capacity_unit.onchange();assert.equal(root.fields.capacity_value.value,'1536');
 root.fields.capacity_unit.value='TB';root.fields.capacity_unit.onchange();await root.nodes.form.onsubmit({preventDefault(){}});
 assert.equal(sent[0].capacity_value,1.5);assert.equal(sent[0].capacity_unit,'TB');assert(!Object.hasOwn(sent[0],'capacity_gib'));
 const old={id:'old',Cliente:'Teste',name:'M365',capacity_gib:1536,selected_sites:[],site_aliases:{}};
 const readonly=new Root();context.mountSharePoint(readonly,async()=>[old],{canEdit:false});await new Promise(r=>setImmediate(r));
 assert(readonly.nodes.new.hidden);assert(readonly.nodes.save.hidden);assert(readonly.nodes.test.hidden);
 await readonly.nodes.cards.onclick({target:{closest:()=>({dataset:{id:'old',action:'edit'}})}});
 assert.equal(readonly.fields.capacity_value.value,'1536');assert.equal(readonly.fields.capacity_unit.value,'GB');
 const stored={...old,capacity_unit:'TB'};const saved=new Root();context.mountSharePoint(saved,async p=>p.endsWith('/sites')?{sites:[]}:[stored]);await new Promise(r=>setImmediate(r));
 await saved.nodes.cards.onclick({target:{closest:()=>({dataset:{id:'old',action:'edit'}})}});
 assert.equal(saved.fields.capacity_value.value,'1.5');assert.equal(saved.fields.capacity_unit.value,'TB');
 console.log('SharePoint UI: guide placement, GB/TB conversion, API payload, legacy and saved units, read-only actions passed (DOM stand-in).');
})().catch(e=>{console.error(e);process.exitCode=1});
