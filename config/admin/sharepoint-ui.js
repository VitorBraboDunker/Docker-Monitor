/* Shared UI: native Grafana app + existing Dunker administration page. */
function mountSharePoint(root, request, options={}) {
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const defaults={name:'',Cliente:'',tenant_id:'',client_id:'',capacity_gib:0,capacity_unit:'GB',interval_hours:24,warning_percent:80,critical_percent:90,emergency_percent:95,stale_hours:96,enabled:true,secret_expires:'',selected_sites:[],site_aliases:{}};
  let tenants=[], current=null, sites=[], dead=false, busy=false;
  const date=t=>t?new Date(t*1000).toLocaleString('pt-BR'):'Ainda não coletado';
  const storage=b=>{const gb=Number(b)/1073741824;return (gb>=1024?gb/1024:gb).toLocaleString('pt-BR',{maximumFractionDigits:2})+(gb>=1024?' TB':' GB')};
  const capacity=t=>{const unit=t.capacity_unit||'GB';return (Number(t.capacity_gib)/(unit==='TB'?1024:1)).toLocaleString('pt-BR',{maximumFractionDigits:6})+' '+unit};
  root.classList.add('dnk-sp');
  root.innerHTML=`<style>${options.css||''}</style><div class="sp-heading"><div><div class="sp-kicker">DUNKER IT · INTEGRAÇÕES</div><h1>SharePoint</h1><p>Consumo de armazenamento e histórico por cliente.</p></div><a class="sp-button" href="/d/dnk-sharepoint-geral">Abrir dashboard</a></div>
  <div class="sp-notice">Coleta diária por padrão. A Microsoft pode publicar os dados com atraso. O limite total do cliente é cadastrado manualmente; limites de sites não são somados.</div>
  <nav class="sp-toolbar"><input data-el="search" aria-label="Buscar integração" placeholder="Buscar cliente ou integração"><button data-el="new" class="sp-primary">+ Integrar cliente</button><button data-el="reload">Atualizar</button><span data-el="count"></span></nav>
  <p data-el="message" role="status" aria-live="polite"></p><div data-el="cards" class="sp-cards"></div>
  <section data-el="editor" class="sp-editor" hidden><div class="sp-heading"><h2 data-el="title">Integrar cliente</h2><button data-el="close" type="button">Fechar</button></div>
  <details class="sp-help" open><summary>Como preparar o Microsoft 365 — passo a passo</summary>
  <ol><li>Acesse <a href="https://entra.microsoft.com/" target="_blank" rel="noopener noreferrer">Microsoft Entra</a> no <strong>tenant do cliente</strong> → Identidade → Aplicativos → Registros de aplicativos → Novo registro. Nome: Dunker Monitor — SharePoint. Selecione somente contas deste diretório. Este fluxo não exige URI de redirecionamento.</li>
  <li>Em <strong>Visão geral</strong>, copie o ID do diretório (Tenant ID) e o ID do aplicativo (Client ID).</li>
  <li>Abra <strong>Permissões de API → Adicionar uma permissão → Microsoft Graph → Permissões de aplicativo</strong>. Adicione <strong>Reports.Read.All</strong>, necessária para o relatório de armazenamento e a descoberta dos sites nesta versão. <strong>Sites.Read.All</strong> é usada em consultas diretas de sites pelo Graph; se já foi concedida, pode permanecer, mas este coletor usa somente o relatório e não a exige. Sites.Selected não substitui Reports.Read.All.</li>
  <li>Clique em <strong>Conceder consentimento do administrador para a organização</strong> e confira o estado concedido da permissão de aplicativo. Permissões delegadas não atendem à coleta automática.</li>
  <li>Em <strong>Certificados e segredos → Segredos do cliente → Novo segredo do cliente</strong>, copie o <strong>Valor</strong> enquanto está visível, guarde no 1Password e anote a expiração. O ID do segredo não funciona como credencial.</li>
  <li>No <a href="https://admin.microsoft.com/" target="_blank" rel="noopener noreferrer">Centro de administração Microsoft 365</a> → Centros de administração → SharePoint → Sites ativos, copie a <strong>capacidade total da organização</strong>. Informe abaixo o valor e escolha <strong>GB ou TB</strong>. 1 TB = 1.024 GB; 0 = não informado. Não some limites individuais de sites.</li>
  <li>Preencha os campos abaixo e clique em <strong>Testar conexão e descobrir sites</strong>. O token e os IDs dos sites são obtidos automaticamente. Este coletor não exige host nem caminho de site preenchidos manualmente. Se precisar identificar um site em outra consulta: host = cliente.sharepoint.com e caminho = /sites/NomeDoSite; para a raiz, /.</li>
  <li>Se nomes/URLs vierem ocultos, use apelidos. Para exibi-los, um administrador global pode avaliar Microsoft 365 → Configurações → Configurações da organização → Serviços → Relatórios → desmarcar a opção de ocultar nomes de usuários, grupos e sites → Salvar. Essa alteração afeta todos os relatórios da organização, não apenas esta integração.</li>
  <li>Confira os sites, selecione todos ou somente os desejados, clique em <strong>Salvar integração</strong> e depois <strong>Coletar agora</strong>. O teste não salva o formulário nem o histórico. Padrões: coleta a cada 24 horas; alertas em 80%, 90% e 95%.</li></ol>
  <p>A integração lê relatórios de uso; não altera arquivos nem limites do SharePoint. O relatório pode refletir dados de 24–48 horas atrás. O servidor precisa de saída HTTPS para login.microsoftonline.com, graph.microsoft.com, reports.office.com e reportsncu.office.com.</p>
  <p><a href="https://learn.microsoft.com/pt-br/graph/api/reportroot-getsharepointsiteusagedetail?view=graph-rest-1.0" target="_blank" rel="noopener noreferrer">Referência oficial: relatório e permissões</a> · <a href="https://learn.microsoft.com/pt-br/sharepoint/manage-site-collection-storage-limits" target="_blank" rel="noopener noreferrer">Capacidade de armazenamento</a></p></details>
  <form data-el="form"><div class="sp-grid">
  <label>Cliente<input name="Cliente" required maxlength="120" placeholder="Ex.: Onkos"></label>
  <label>Nome da integração<input name="name" required maxlength="120" placeholder="Ex.: Microsoft 365 — matriz"></label>
  <label>Estado<select name="enabled"><option value="true">Ativo</option><option value="false">Pausado</option></select></label>
  <label>Tenant ID<input name="tenant_id" required placeholder="ID do diretório no Entra"></label>
  <label>Application / Client ID<input name="client_id" required placeholder="ID do aplicativo no Entra"></label>
  <label>Valor do segredo<input name="client_secret" type="password" autocomplete="new-password" placeholder="Ao editar, vazio mantém o segredo"></label>
  <label>Expiração do segredo (opcional)<input name="secret_expires" type="date"></label>
  <label>Capacidade total do cliente<div class="sp-capacity"><input name="capacity_value" aria-label="Valor da capacidade total" type="number" min="0" max="100000000" step="any" required><select name="capacity_unit" aria-label="Unidade da capacidade"><option value="GB">GB</option><option value="TB">TB</option></select></div><small data-el="capacityHint">1 TB = 1.024 GB (unidades do SharePoint). 0 = não informado.</small></label>
  <label>Consultar a cada (horas)<input name="interval_hours" type="number" min="6" max="168" step="any"></label>
  <label>Atenção (%)<input name="warning_percent" type="number" min="1" max="100" step="any"></label>
  <label>Crítico (%)<input name="critical_percent" type="number" min="1" max="100" step="any"></label>
  <label>Emergência (%)<input name="emergency_percent" type="number" min="1" max="100" step="any"></label>
  <label>Dados antigos após (horas)<input name="stale_hours" type="number" min="48" max="720" step="any"></label>
  </div>
  <div class="sp-actions"><button type="button" data-el="test">Testar conexão e descobrir sites</button><button type="submit" data-el="save" class="sp-primary">Salvar integração</button></div>
  <p data-el="result" role="status" aria-live="polite"></p>
  <div class="sp-sites"><div class="sp-toolbar"><h3>Sites acompanhados</h3><select data-el="selection" aria-label="Seleção de sites"><option value="all">Todos os sites (inclui novos automaticamente)</option><option value="selected">Somente os selecionados</option></select></div>
  <p>O consumo geral do cliente considera todos os sites ativos do relatório. A seleção controla o detalhamento por site.</p><div class="sp-tablewrap"><table><thead><tr><th>Acompanhar</th><th>Site / identificação</th><th>Uso</th><th>Limite do site</th><th>Apelido (opcional)</th></tr></thead><tbody data-el="siteRows"></tbody></table></div><p data-el="siteEmpty">Salve e colete, ou teste a conexão para descobrir os sites.</p></div></form></section>`;
  const $=id=>root.querySelector(`[data-el="${id}"]`), form=$('form');
  const msg=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('sp-error',error)};
  const status=t=>!t.enabled?'Pausado':t.collecting?'Coletando':t.error?'Falha na coleta':!t.report_date?'Aguardando coleta':(Date.now()-Date.parse(t.report_date+'T00:00:00Z'))>t.stale_hours*3600000?'Relatório antigo':t.capacity_gib===0?'Capacidade não informada':'Coleta disponível';
  function render(){
    if(dead)return;const q=$('search').value.toLowerCase();$('count').textContent=tenants.length+' integrações';
    const filtered=tenants.filter(t=>(t.Cliente+' '+t.name).toLowerCase().includes(q));
    $('cards').innerHTML=filtered.length?filtered.map(t=>`<article class="sp-card"><div class="sp-kicker">${esc(t.Cliente)}</div><h2>${esc(t.name)}</h2><span class="sp-badge ${t.error?'sp-bad':''}">${esc(status(t))}</span><dl><dt>Relatório da Microsoft</dt><dd>${esc(t.report_date||'—')}</dd><dt>Última coleta bem-sucedida</dt><dd>${esc(date(t.last_success))}</dd><dt>Capacidade cadastrada</dt><dd>${t.capacity_gib?esc(capacity(t)):'Não informada'}</dd></dl>${t.error?'<p class="sp-error">'+esc(t.error)+'</p>':''}${t.report_warning?'<p class="sp-notice">'+esc(t.report_warning)+'</p>':''}<div class="sp-actions"><button data-id="${esc(t.id)}" data-action="edit">Configurar</button><button data-id="${esc(t.id)}" data-action="collect" ${t.collecting?'disabled':''}>Coletar agora</button><button data-id="${esc(t.id)}" data-action="pause">${t.enabled?'Pausar':'Ativar'}</button><button data-id="${esc(t.id)}" data-action="export">Exportar histórico</button><button data-id="${esc(t.id)}" data-action="delete" class="sp-danger">Excluir</button></div></article>`).join(''):'<div class="sp-empty"><h2>Nenhuma integração encontrada</h2><p>Cadastre um cliente para acompanhar o armazenamento do SharePoint.</p></div>';
    if(options.canEdit===false){root.querySelectorAll('[data-action=collect],[data-action=pause],[data-action=delete]').forEach(b=>b.hidden=true);root.querySelectorAll('[data-action=edit]').forEach(b=>b.textContent='Consultar configuração')}
  }
  async function load(){try{const list=await request('/tenants');if(dead)return;tenants=list;render()}catch(e){if(!dead)msg(e.message,true)}}
  function gatherSites(){return [...$('siteRows').querySelectorAll('tr')].map(r=>({id:r.dataset.id,checked:r.querySelector('input[type=checkbox]').checked,alias:r.querySelector('input[type=text]').value.trim()}))}
  function showSites(list, cfg=current||defaults){sites=list;$('siteEmpty').hidden=!!list.length;
    $('siteRows').innerHTML=list.map(s=>`<tr data-id="${esc(s.site_id)}"><td><input type="checkbox" ${!cfg.selected_sites?.length||cfg.selected_sites.includes(s.site_id)?'checked':''} aria-label="Acompanhar ${esc(s.site_name)}"></td><td><strong>${esc(s.site_name)}</strong><small>${esc(s.url||s.site_id)}</small></td><td>${esc(storage(s.used_bytes))}</td><td>${esc(storage(s.quota_bytes))}</td><td><input type="text" maxlength="120" value="${esc(cfg.site_aliases?.[s.site_id]||'')}" aria-label="Apelido de ${esc(s.site_name)}"></td></tr>`).join('');
    selectionChanged();
    if(!canEdit)root.querySelectorAll('.sp-sites input').forEach(x=>x.disabled=true);
  }
  function selectionChanged(){root.querySelectorAll('.sp-sites input[type=checkbox]').forEach(x=>{x.disabled=options.canEdit===false||$('selection').value==='all'})}
  async function open(t){current=t||null;const v={...defaults,...t};form.reset();$('result').textContent='';$('title').textContent=t?'Configurar '+t.Cliente:'Integrar cliente';
    for(const k in defaults){const field=form.elements.namedItem(k);if(field)field.value=String(v[k])}
    form.elements.capacity_unit.value=v.capacity_unit||'GB';
    form.elements.capacity_value.value=String(Number(v.capacity_gib)/(form.elements.capacity_unit.value==='TB'?1024:1));
    capacityUnit=form.elements.capacity_unit.value;updateCapacityHint();
    form.elements.tenant_id.readOnly=!!t;form.elements.client_id.readOnly=!!t;form.elements.client_secret.required=!t;
    $('selection').value=v.selected_sites.length?'selected':'all';showSites([],v);if(options.canEdit===false)form.querySelectorAll('input,select').forEach(x=>x.disabled=true);$('editor').hidden=false;$('editor').scrollIntoView({behavior:'smooth',block:'start'});
    if(t)try{const r=await request('/tenants/'+t.id+'/sites');if(!dead&&current?.id===t.id)showSites(r.sites,v)}catch(e){if(!dead)$('result').textContent=e.message}
  }
  function payload(){const p={};for(const k in defaults){const f=form.elements.namedItem(k);if(f)p[k]=f.value}
    for(const k of ['interval_hours','warning_percent','critical_percent','emergency_percent','stale_hours'])p[k]=Number(p[k]);
    p.capacity_value=Number(form.elements.capacity_value.value);p.capacity_unit=form.elements.capacity_unit.value;
    p.enabled=p.enabled==='true';if(current)p.id=current.id;const secret=form.elements.client_secret.value;if(secret)p.client_secret=secret;
    const chosen=gatherSites();p.selected_sites=$('selection').value==='all'?[]:chosen.filter(s=>s.checked).map(s=>s.id);
    if($('selection').value==='selected'&&!p.selected_sites.length)throw Error('Selecione pelo menos um site ou escolha todos os sites.');
    // Retain selections/aliases while a saved report has not yet loaded.
    if(!sites.length&&current?.selected_sites?.length)p.selected_sites=current.selected_sites;
    p.site_aliases={...(current?.site_aliases||{})};for(const s of chosen){if(s.alias)p.site_aliases[s.id]=s.alias;else delete p.site_aliases[s.id]}
    return p;
  }
  let capacityUnit='GB';
  function updateCapacityHint(){const value=Number(form.elements.capacity_value.value),unit=form.elements.capacity_unit.value,gb=value*(unit==='TB'?1024:1);$('capacityHint').textContent=gb>0?(unit==='TB'?gb:gb/1024).toLocaleString('pt-BR',{maximumFractionDigits:6})+' '+(unit==='TB'?'GB':'TB')+' · 1 TB = 1.024 GB (unidades do SharePoint).':'0 = não informado. 1 TB = 1.024 GB (unidades do SharePoint).'}
  form.elements.capacity_unit.onchange=()=>{const unit=form.elements.capacity_unit.value,value=Number(form.elements.capacity_value.value);if(Number.isFinite(value))form.elements.capacity_value.value=String(value*(capacityUnit==='TB'?1024:1)/(unit==='TB'?1024:1));capacityUnit=unit;updateCapacityHint()};
  form.elements.capacity_value.oninput=updateCapacityHint;
  async function job(start,onStatus){const r=await start;let polls=0;
    while(!dead&&polls++<240){const j=await request('/jobs/'+r.job_id);if(j.state==='done')return j.result;if(j.state==='error')throw Error(j.error);onStatus?.('Consultando a Microsoft…');await new Promise(resolve=>setTimeout(resolve,1000))}
    if(dead)return null;throw Error('A operação continua no servidor. Atualize a lista para conferir o resultado.');
  }
  const canEdit=options.canEdit!==false;
  const setBusy=v=>{if(dead)return;busy=v;$('save').disabled=v||!canEdit;$('test').disabled=v||!canEdit;$('close').disabled=v};
  form.onsubmit=async e=>{e.preventDefault();if(!canEdit||busy)return;setBusy(true);try{await request(current?'/tenants/'+current.id:'/tenants',{method:current?'PUT':'POST',body:JSON.stringify(payload())});if(dead)return;form.elements.client_secret.value='';$('editor').hidden=true;msg('Integração salva. O coletor executa conforme o intervalo; use Coletar agora para iniciar.');await load()}catch(e){if(!dead)$('result').textContent=e.message}finally{setBusy(false)}};
  $('test').onclick=async()=>{if(!canEdit||busy||!form.reportValidity())return;setBusy(true);$('result').textContent='Testando conexão…';try{const p=payload(),r=await job(request('/test',{method:'POST',body:JSON.stringify(p)}));if(!r||dead)return;showSites(r.sites,{...current,selected_sites:p.selected_sites,site_aliases:p.site_aliases});$('result').textContent=`Conexão confirmada · ${r.site_count} sites · ${storage(r.used_bytes)} · relatório de ${r.report_date}. ${r.warning||''}`;form.elements.client_secret.value=p.client_secret||''}catch(e){if(!dead)$('result').textContent=e.message}finally{setBusy(false)}};
  $('cards').onclick=async e=>{const b=e.target.closest('button[data-id]');if(!b||b.disabled)return;const t=tenants.find(x=>x.id===b.dataset.id);if(b.dataset.action==='edit')return open(t);if(!canEdit&&b.dataset.action!=='export')return;b.disabled=true;
    try{switch(b.dataset.action){case 'collect':msg('Coletando '+t.Cliente+'…');{const collected=await job(request('/tenants/'+t.id+'/collect',{method:'POST',body:'{}'}));msg('Coleta concluída. Os painéis recebem as métricas em até 5 minutos. '+(collected?.warning||''));}break;
      case 'pause':await request('/tenants/'+t.id,{method:'PUT',body:JSON.stringify({enabled:!t.enabled})});msg(t.enabled?'Coleta pausada.':'Coleta ativada.');break;
      case 'delete':if(!confirm('Excluir a integração? O histórico fica preservado até expirar; a credencial será removida.'))return;await request('/tenants/'+t.id,{method:'DELETE'});msg('Integração excluída.');break;
      case 'export':{const data=await request('/tenants/'+t.id+'/export',{},true),url=URL.createObjectURL(new Blob([data],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='sharepoint-historico-'+t.id+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);break}}
      await load();}catch(e){msg(e.message,true)}finally{b.disabled=false}
  };
  $('new').onclick=()=>open();$('close').onclick=()=>{$('editor').hidden=true;form.elements.client_secret.value='';current=null};$('reload').onclick=load;$('search').oninput=render;$('selection').onchange=selectionChanged;
  if(!canEdit){['new','save','test'].forEach(id=>$(id).hidden=true);$('title').textContent='Consultar integração';}
  load();const timer=setInterval(()=>{if(!busy)load()},30000);
  return ()=>{dead=true;clearInterval(timer);root.innerHTML='';};
}
