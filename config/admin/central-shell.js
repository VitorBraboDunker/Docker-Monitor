// Same origin as Grafana: HttpOnly session cookies stay in the browser.
const centralPages={links:'Links e disponibilidade',snmp:'Firewalls e SNMP',sharepoint:'SharePoint',servidores:'Servidores e histórico',alloy:'Agentes Alloy',excluidos:'Itens excluídos',dominios:'Domínios e certificados',permissoes:'Permissões'};
function centralAllowed(area,me){return ['permissoes','dominios'].includes(area)?me.manage_access:area==='excluidos'?Object.values(me.permissions).some(p=>p!=='none'):area==='alloy'?me.permissions.servidores!=='none':me.permissions[area]!=='none'}
function centralLoginUrl(){return '/login?redirectTo='+encodeURIComponent(window.location.pathname)}
async function centralRequest(path,opt={},asText=false){
 const r=await fetch('/monitoramento'+path,{...opt,credentials:'same-origin',redirect:'error',cache:'no-store',headers:{'Content-Type':'application/json'}});
 if(r.status===401){window.location.replace(centralLoginUrl());throw Error('Sessão encerrada. Entre novamente no Grafana.')}
 const data=asText?await r.text():await r.json().catch(()=>({}));
 if(!r.ok)throw Error(data.error||'Falha na operação.');return data;
}
async function bootCentral(){
 const content=document.getElementById('content'),nav=document.getElementById('navigation'),identity=document.getElementById('identity');
 const area=window.location.pathname.split('/').filter(Boolean).pop();
 try{
 const me=await centralRequest('/api/access/me');
 identity.textContent=me.login+' · '+me.role+' · '+me.profile;
 for(const [key,title] of Object.entries(centralPages))if(centralAllowed(key,me)){const a=document.createElement('a');a.href='/monitoramento/central/'+key;a.textContent=title;if(key===area)a.setAttribute('aria-current','page');nav.appendChild(a)}
 document.title=(centralPages[area]||'Integrações')+' · Dunker Monitor';
 if(!centralPages[area]||!centralAllowed(area,me)){content.textContent='Seu perfil não tem acesso a esta integração.';return}
 content.innerHTML='';const host=document.createElement('div');content.appendChild(host);
 let dispose;
 if(['servidores','alloy','excluidos','dominios'].includes(area))dispose=mountOperations(host,centralRequest,area,me);
 else if(area==='permissoes')dispose=mountAccess(host,centralRequest);
 else if(area==='sharepoint')dispose=mountSharePoint(host,(p,o,t)=>centralRequest('/api/sharepoint'+p,o,t),{css:sharepointCss,canEdit:me.permissions.sharepoint==='edit'});
 else dispose=mountLinks(host,centralRequest,area,me.permissions[area]==='edit');
 window.addEventListener('pagehide',()=>{if(dispose)dispose()},{once:true});
 }catch(e){identity.textContent='Não foi possível verificar a sessão.';content.textContent=e.message;content.classList.add('central-error')}
}
bootCentral();
