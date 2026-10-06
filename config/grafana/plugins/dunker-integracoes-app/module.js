System.register(["react","@grafana/data","@grafana/runtime"],function(exports){
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
