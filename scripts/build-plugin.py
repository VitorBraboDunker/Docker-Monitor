#!/usr/bin/env python3
"""Build the standalone central and the Grafana launcher without a frontend toolchain."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ui=(root/'config/admin/sharepoint-ui.js').read_text()
css=(root/'config/admin/sharepoint.css').read_text()
operations=(root/'config/admin/operations-ui.js').read_text()
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
if(typeof document!=='undefined'&&document.body.classList.contains('theme-dark'))host.classList.add('theme-dark');
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
# The full UI lives in a standalone same-origin page. Grafana only launches it.
central=(root/'config/admin/central-shell.js').read_text()
(root/'config/admin/central.js').write_text(ui+'\nconst sharepointCss='+json.dumps(css)+';\n'+access+'\n'+operations+'\n'+links+'\n'+central)
launcher=r'''System.register(["react","@grafana/data","@grafana/runtime"],function(exports){
let React,AppPlugin,config;
return {setters:[m=>{React=m},m=>{AppPlugin=m.AppPlugin},m=>{config=m.config||{}}],execute:function(){
const pages=['links','snmp','sharepoint','servidores','alloy','excluidos','dominios','permissoes'];
function Root(){
 const requested=window.location.pathname.split('/').filter(Boolean).pop();
 const area=pages.includes(requested)?requested:'links';
 const url=(config.appSubUrl||'')+'/monitoramento/central/'+area;
 React.useEffect(()=>{window.location.replace(url)},[url]);
 return React.createElement('div',{style:{padding:'24px'}},React.createElement('h2',null,'Central de integrações'),React.createElement('p',null,'Abrindo a central com sua sessão do Grafana…'),React.createElement('a',{href:url},'Abrir central de integrações'));
}
exports('plugin',new AppPlugin().setRootPage(Root));
}};});
'''
(root/'config/grafana/plugins/dunker-integracoes-app/module.js').write_text(launcher)
