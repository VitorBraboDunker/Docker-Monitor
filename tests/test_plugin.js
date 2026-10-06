const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..'),bundle=fs.readFileSync(path.join(root,'config/grafana/plugins/dunker-integracoes-app/module.js'),'utf8');
let exportsMap={},dependencies;
class AppPlugin{setRootPage(page){assert.equal(typeof page,'function');this.rootPage=page;return this}}
const System={register(deps,factory){dependencies=deps;const registration=factory((key,value)=>{exportsMap[key]=value});registration.setters[0]({});registration.setters[1]({AppPlugin});registration.setters[2]({getBackendSrv:()=>{}});registration.execute();}};
vm.runInNewContext(bundle,{System,console});assert(exportsMap.plugin instanceof AppPlugin);
assert.deepEqual(dependencies,['react','@grafana/data','@grafana/runtime']);
const meta=JSON.parse(fs.readFileSync(path.join(root,'config/grafana/plugins/dunker-integracoes-app/plugin.json')));
assert(!meta.routes,'No token-only route may bypass per-user permissions');
assert.equal(meta.includes.length,8);assert.equal(meta.includes.find(i=>i.path.endsWith('/permissoes')).role,'Admin');
assert(bundle.includes('credentials:\'same-origin\''));
assert(bundle.includes('mountLinks'));assert(bundle.includes('mountAccess'));
assert(!bundle.includes('gatewayToken'));assert(bundle.includes(fs.readFileSync(path.join(root,'config/admin/sharepoint-ui.js'),'utf8')));
console.log('Plugin: SystemJS registration, 8 native pages and same-origin session requests OK. Live Grafana validation remains required.');
