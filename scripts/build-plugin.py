#!/usr/bin/env python3
"""Build native Grafana pages from shared UI, without a frontend toolchain."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ui=(root/'config/admin/sharepoint-ui.js').read_text()
css=(root/'config/admin/sharepoint.css').read_text()
access=(root/'config/admin/access-ui.js').read_text()
html=(root/'config/admin/index.html').read_text()
links_css=re.search(r'<style>(.*?)</style>',html,re.S).group(1).replace('body{',':host{')
markup=re.search(r'<body>(.*?)<script>',html,re.S).group(1)
# The Grafana page shell owns navigation; retain complete existing forms.
markup=re.sub(r'<header>.*?</header>','',markup,flags=re.S)
markup=re.sub(r'<nav class="bar">.*?</nav>','',markup,count=1,flags=re.S)
script=re.search(r'<script>(.*?)</script>',html,re.S).group(1)
script=script.replace("async function api(path,opt={}){const r=await fetch('api/'+path,{...opt,headers:{'Content-Type':'application/json'}});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.error||'Falha na operação');return j}", "const api=(path,opt={})=>request('/api/'+path,opt);")
script=script.replace("typeChanged();load();", "typeChanged();if(area==='links')load();")
script=script.replace("$('tabLinks').onclick=()=>switchTab(false);$('tabDevices').onclick=()=>switchTab(true);", "")
script=re.sub(r"(?m)^function switchTab\(dev\).*\n", "", script)
script=script.replace("document.getElementById(id)","root.getElementById(id)")
script=script.replace("document.querySelectorAll", "root.querySelectorAll")
links='''function mountLinks(host,request,area,canEdit){
const root=host.attachShadow({mode:'open'});
root.innerHTML='<style>'+'''+json.dumps(links_css)+'''+'</style>'+'''+json.dumps(markup)+''';
const readonly=()=>{if(canEdit)return;
 const ids=area==='links'?['new','save','test']:['deviceNew','deviceSave','deviceTest'];
 ids.forEach(id=>{const x=root.getElementById(id);if(x&&!x.hidden)x.hidden=true});
 root.querySelectorAll('form input,form select').forEach(x=>{if(!x.disabled)x.disabled=true});
 root.querySelectorAll('[data-action=delete],[data-op=pause],[data-op=delete]').forEach(x=>{if(!x.hidden)x.hidden=true});
 root.querySelectorAll('[data-action=edit],[data-op=edit]').forEach(x=>{if(x.textContent!=='Consultar')x.textContent='Consultar'});
};
root.addEventListener('submit',e=>{if(!canEdit){e.preventDefault();e.stopImmediatePropagation()}},true);
const observer=new MutationObserver(readonly);observer.observe(root,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','hidden']});
'''+script+'''
$('linksSection').classList.toggle('hidden',area!=='links');$('deviceSection').classList.toggle('hidden',area!=='snmp');if(area==='snmp')loadDevices();readonly();
return ()=>{observer.disconnect();root.querySelectorAll('dialog[open]').forEach(d=>d.close());host.remove()};
}
'''
shell=r'''
const base='/a/dunker-integracoes-app/';
async function request(path,opt={},asText=false){
 const r=await fetch((config.appSubUrl||'')+'/monitoramento'+path,{...opt,credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/json'}});
 const data=asText?await r.text():await r.json().catch(()=>({}));
 if(!r.ok)throw Error(data.error||(r.status===401?'Entre novamente no Grafana.':'Falha na operação.'));
 return data;
}
const names={links:'Links e disponibilidade',snmp:'Firewalls e SNMP',sharepoint:'SharePoint',permissoes:'Permissões'};
const commonCss=`.dnk-native{padding:20px;max-width:1440px;margin:auto;font-family:inherit}.dnk-native nav{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.dnk-native button,.dnk-native select,.dnk-native input{padding:9px 12px;border:1px solid #b4c0d2;border-radius:7px;font:inherit}.dnk-native button{cursor:pointer;background:#e7eef9;color:#122952}.dnk-native button:disabled{opacity:.5}.dnk-native .dnk-primary{background:#2869d8;color:white}.dnk-native .dnk-card{padding:20px;border:1px solid #8895aa66;border-radius:10px;margin-bottom:20px;overflow:auto}.dnk-native table{width:100%;border-collapse:collapse}.dnk-native td,.dnk-native th{padding:10px;text-align:left;border-bottom:1px solid #8895aa55}.dnk-native small{display:block}.dnk-native label{display:inline-grid;gap:8px;margin:8px 20px 8px 0}.dnk-native [hidden]{display:none!important}.dnk-native .dnk-status{opacity:.8}`;
function Root(){
 const ref=React.useRef(null),[me,setMe]=React.useState(null),[error,setError]=React.useState('');
 const area=window.location.pathname.split('/').filter(Boolean).pop();
 React.useEffect(()=>{let dead=false;request('/api/access/me').then(m=>{if(!dead)setMe(m)}).catch(e=>{if(!dead)setError(e.message)});return()=>{dead=true}},[]);
 React.useEffect(()=>{if(!me||!ref.current)return;
 const host=ref.current;host.innerHTML='';
 if(!names[area]){host.textContent='Selecione uma integração acima.';return}
 const allowed=area==='permissoes'?me.manage_access:me.permissions[area]!=='none';
 if(!allowed){host.textContent='Seu perfil não tem acesso a esta configuração.';return}
 const content=document.createElement('div');host.appendChild(content);
 if(area==='permissoes')return mountAccess(content,request);
 if(area==='sharepoint')return mountSharePoint(content,(p,o,t)=>request('/api/sharepoint'+p,o,t),{css,canEdit:me.permissions.sharepoint==='edit'});
 return mountLinks(content,request,area,me.permissions[area]==='edit');
 },[me,area]);
 const nav=me?Object.keys(names).filter(a=>a==='permissoes'?me.manage_access:me.permissions[a]!=='none').map(a=>React.createElement('button',{key:a,className:a===area?'dnk-primary':'',onClick:()=>window.location.assign((config.appSubUrl||'')+base+a)},names[a])):[];
 return React.createElement('section',{className:'dnk-native'},React.createElement('style',null,commonCss),
 React.createElement('h2',null,'Dunker · Integrações'),
 React.createElement('p',{className:'dnk-status'},me?me.login+' · '+me.role+' · Perfil: '+me.profile:'Verificando sessão do Grafana…'),
 error?React.createElement('p',{role:'alert'},error):null,React.createElement('nav',null,...nav),React.createElement('div',{ref}));
}
exports('plugin',new AppPlugin().setRootPage(Root));
'''
bundle='''System.register(["react","@grafana/data","@grafana/runtime"],function(exports){
let React,AppPlugin,config;
return {setters:[m=>{React=m},m=>{AppPlugin=m.AppPlugin},m=>{config=m.config||{}}],execute:function(){
'''+ui+'\nconst css='+json.dumps(css)+';\n'+access+'\n'+links+'\n'+shell+'\n}};});\n'
(root/'config/grafana/plugins/dunker-integracoes-app/module.js').write_text(bundle)
