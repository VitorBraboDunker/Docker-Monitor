#!/usr/bin/env python3
"""Visual administration for Dunker Monitor ICMP targets (stdlib only)."""
from __future__ import annotations

import base64
import hmac
import http.server
import ipaddress
import json
import os
import re
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


DATA_DIR = Path(os.environ.get("DNK_ADMIN_DATA", "/data"))
INVENTORY = DATA_DIR / "inventory.json"
ICMP_TARGETS = DATA_DIR / "icmp.json"
BLACKBOX_URL = os.environ.get("BLACKBOX_URL", "http://blackbox:9115")
PASSWORD_FILE = Path(os.environ.get("ADMIN_PASSWORD_FILE", "/run/secrets/admin_password"))
PORT = int(os.environ.get("ADMIN_PORT", "8080"))
LOCK = threading.RLock()

DEFAULTS = {
    "tipo": "icmp",
    "enabled": True,
    "interval_seconds": 30,
    "timeout_seconds": 5,
    "packet_count": 5,
    "packet_interval_seconds": 1,
    "latency_warning_ms": 100,
    "loss_warning_percent": 5,
}


def read_password() -> str:
    try:
        return PASSWORD_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_inventory() -> list[dict]:
    try:
        value = json.loads(INVENTORY.read_text(encoding="utf-8"))
        
        if not isinstance(value, list):
            raise ValueError("Inventário inválido: lista esperada")
        return value
    except FileNotFoundError:
        return []


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


SUPPORTED = {'icmp', 'http', 'tcp', 'dns'}

def persist(rows: list[dict]) -> None:
    atomic_json(INVENTORY, rows)
    for kind in ('icmp', 'http', 'tcp'):
        targets=[]
        for row in rows:
            if row.get('tipo') != kind or not row.get('enabled', True):continue
            # Managed HTTP/TCP checks use the scheduled multiprotocol exporter.
            if kind != 'icmp' and row.get('id'):continue
            labels={key:row[key] for key in ('Cliente','Unidade','Provedor')}
            if row.get('id'):labels.update(monitor_id=row['id'],monitor_name=row['name'])
            targets.append({'targets':[row['instance']], 'labels':labels})
        atomic_json(DATA_DIR / (kind+'.json'), targets)


def bounded_number(value, label, minimum, maximum, integer=False):
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: valor inválido")
    if not minimum <= number <= maximum:
        raise ValueError(f"{label}: use um valor entre {minimum} e {maximum}")
    return number


def normalize(payload: dict, current: dict | None = None) -> dict:
    row = dict(DEFAULTS)
    if current:
        row.update(current)
    row.update(payload)
    row["id"] = str(uuid.UUID(current["id"])) if current else str(uuid.uuid4())
    row["name"] = str(row.get("name", "")).strip()
    for field in ("Cliente", "Unidade", "Provedor"):
        row[field] = str(row.get(field, "")).strip()
    from monitor_probes import validate_host
    kind = row.get('tipo', 'icmp')
    if kind not in SUPPORTED:raise ValueError('Tipo de verificação inválido')
    row['instance']=str(row.get('instance','')).strip()
    if kind=='icmp':row['instance']=str(ipaddress.IPv4Address(row['instance']))
    elif kind=='http':
        url=urllib.parse.urlsplit(row['instance'])
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
            raise ValueError('Use uma URL HTTP/HTTPS sem credenciais no endereço')
        validate_host(url.hostname)
        if url.port is not None and not 1<=url.port<=65535:raise ValueError('Porta inválida')
        row['http_method']=str(row.get('http_method','GET')).upper()
        if row['http_method'] not in ('GET','HEAD'):raise ValueError('Método permitido: GET ou HEAD')
        row['expected_status']=bounded_number(row.get('expected_status',0),'Código HTTP esperado',0,599,True)
        if row['expected_status'] and row['expected_status']<100:raise ValueError('Código HTTP inválido')
        row['follow_redirects']=row.get('follow_redirects',True)
        if not isinstance(row['follow_redirects'],bool):raise ValueError('Redirecionamento deve ser verdadeiro ou falso')
    elif kind=='tcp':
        if row.get('tcp_host'):
            host=validate_host(row['tcp_host']);port=row.get('tcp_port')
        else:
            host,sep,port=row['instance'].rpartition(':')
            if not sep:raise ValueError('Informe host e porta TCP')
            host=validate_host(host.strip('[]'))
        row['tcp_host']=host;row['tcp_port']=bounded_number(port,'Porta TCP',1,65535,True)
        row['instance']=f"[{host}]:{row['tcp_port']}" if ':' in host else f"{host}:{row['tcp_port']}"
    else:
        row['instance']=validate_host(row['instance'])
        row['dns_name']=validate_host(row.get('dns_name',''))
        row['dns_type']=str(row.get('dns_type','A')).upper()
        if row['dns_type'] not in ('A','AAAA','CNAME','MX','TXT','NS'):raise ValueError('Tipo DNS inválido')
        row['dns_port']=bounded_number(row.get('dns_port',53),'Porta DNS',1,65535,True)
    if not row["name"] or any(not row[x] for x in ("Cliente", "Unidade", "Provedor")):
        raise ValueError("Preencha nome, cliente, unidade e provedor")
    row["interval_seconds"] = bounded_number(row.get("interval_seconds"), "Frequência", 10, 3600, True)
    row["timeout_seconds"] = bounded_number(row.get("timeout_seconds"), "Timeout", 1, 30)
    row["packet_count"] = bounded_number(row.get("packet_count"), "Pacotes", 1, 20, True)
    row["packet_interval_seconds"] = bounded_number(row.get("packet_interval_seconds"), "Intervalo dos pacotes", 0.1, 10)
    row["latency_warning_ms"] = bounded_number(row.get("latency_warning_ms"), "Limite de latência", 1, 10000)
    row["loss_warning_percent"] = bounded_number(row.get("loss_warning_percent"), "Limite de perda", 0, 100)
    if not isinstance(row.get("enabled", True), bool):
        raise ValueError("Estado deve ser verdadeiro ou falso")
    row["enabled"] = row.get("enabled", True)
    row["tipo"] = kind
    row.pop("criticality", None)
    return row


def test_target(payload: dict) -> dict:
    from ping_exporter import probe
    row=normalize(payload)
    if row['tipo']!='icmp':
        from monitor_probes import probe_service
        result=probe_service(row)
        return dict(result,duration_ms=round(result['duration']*1000,2),tipo=row['tipo'])
    address = row['instance']
    timeout = bounded_number(payload.get("timeout_seconds", 5), "Timeout", 1, 30)
    count = bounded_number(payload.get("packet_count", 5), "Pacotes", 1, 20, True)
    interval = bounded_number(payload.get("packet_interval_seconds", 1), "Intervalo", 0.1, 10)
    result = probe(address, count, timeout, interval)
    return {"success": result["received"] > 0, "collector_success": bool(result["success"]),
            "duration_ms": round(result["duration"] * 1000, 2), "target": address,
            "received": result["received"], "sent": result["sent"],
            "loss_percent": result["loss"] if result["success"] else None,
            "rtt_ms": round(result["rtt"] * 1000, 2) if result["received"] else None}


PAGE = r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dunker · Verificações</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fb;color:#172b4d;font:14px 'Segoe UI',sans-serif}header{background:#122952;color:white;padding:24px}header h1{margin:0;font-size:22px}header a{color:white;float:right}main{max-width:1200px;margin:24px auto;padding:0 16px}.bar,.card{background:white;padding:18px;border:1px solid #dae3ef;border-radius:12px;margin-bottom:16px}.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}input,select{padding:10px;border:1px solid #bccbde;border-radius:7px;width:100%;font:inherit}button{padding:10px 14px;border:0;border-radius:7px;cursor:pointer;background:#e7eef9;color:#122952;font-weight:600}.primary{background:#2869d8;color:white}.danger{color:#aa2424;background:#ffeded}table{width:100%;border-collapse:collapse}td,th{padding:12px;text-align:left;border-bottom:1px solid #e6edf5}th{color:#65758f;font-size:12px}.muted{color:#6b7e96}dialog{border:0;border-radius:14px;width:min(860px,95vw);max-height:92vh;padding:24px}dialog::backdrop{background:#12295299}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.wide{grid-column:1/-1}label{display:block;font-weight:600;margin-bottom:6px}small{color:#677c98}.actions{display:flex;gap:8px;justify-content:flex-end;margin-top:20px}.notice{padding:12px;background:#eef4ff;border-radius:8px;margin-top:14px;white-space:pre-wrap}#message{color:#b3261e}#search{max-width:420px}.hidden{display:none!important}@media(max-width:700px){.grid{grid-template-columns:1fr}.tablewrap{overflow:auto}}
</style></head><body><header><a href="/">Voltar ao Grafana</a><h1>DUNKER IT · Verificações</h1><p>Disponibilidade de links, sites, portas e DNS</p></header><main><div class="bar"><input id="search" placeholder="Buscar cliente, nome ou destino"><button class="primary" id="new">+ Nova verificação</button><button id="reload">Atualizar</button><span id="summary" class="muted"></span></div><p id="message" role="alert"></p><div class="card tablewrap"><table><thead><tr><th>Nome / tipo</th><th>Cliente / unidade</th><th>Destino</th><th>Frequência</th><th>Estado</th><th>Ações</th></tr></thead><tbody id="rows"></tbody></table><p id="empty">Nenhuma verificação encontrada.</p></div></main>
<dialog id="modal"><form id="form"><h2 id="title">Nova verificação</h2><input id="id" type="hidden"><div class="grid">
<div><label>Tipo de verificação</label><select id="tipo"><option value="icmp">Ping — ICMP</option><option value="http">HTTP / HTTPS</option><option value="tcp">TCP</option><option value="dns">DNS</option></select></div><div class="wide"><label>Nome da verificação</label><input id="name" required placeholder="Ex.: Onkos SP — link Claro"></div>
<div><label>Cliente</label><input id="Cliente" required></div><div><label>Unidade</label><input id="Unidade" required></div><div><label>Provedor / serviço</label><input id="Provedor" required></div>
<div class="wide"><label id="destinationLabel">IP de destino</label><input id="instance" required><small id="destinationHint"></small></div>
<div data-types="tcp"><label>Porta TCP</label><input id="tcp_port" type="number" min="1" max="65535" value="443"></div>
<div data-types="http"><label>Método</label><select id="http_method"><option>GET</option><option>HEAD</option></select></div><div data-types="http"><label>Código HTTP esperado</label><input id="expected_status" type="number" min="0" max="599" value="0"><small>0 = qualquer código de 200 a 299</small></div><div data-types="http"><label>Seguir redirecionamentos</label><select id="follow_redirects"><option value="true">Sim</option><option value="false">Não</option></select></div>
<div data-types="dns"><label>Nome a consultar</label><input id="dns_name" placeholder="exemplo.com.br"></div><div data-types="dns"><label>Registro DNS</label><select id="dns_type"><option>A</option><option>AAAA</option><option>CNAME</option><option>MX</option><option>TXT</option><option>NS</option></select></div><div data-types="dns"><label>Porta DNS</label><input id="dns_port" type="number" min="1" max="65535" value="53"></div>
<div><label>Executar a cada (segundos)</label><input id="interval_seconds" type="number" min="10" max="3600" value="30" required></div><div><label id="timeoutLabel">Timeout por pacote (segundos)</label><input id="timeout_seconds" type="number" min="1" max="30" step="0.5" value="5" required></div><div><label>Estado</label><select id="enabled"><option value="true">Ativo</option><option value="false">Pausado</option></select></div>
<div data-types="icmp"><label>Quantidade de pacotes</label><input id="packet_count" type="number" min="1" max="20" value="5"></div><div data-types="icmp"><label>Intervalo entre pacotes (segundos)</label><input id="packet_interval_seconds" type="number" min="0.1" max="10" step="0.1" value="1"></div><div data-types="icmp"><label>Limite de perda (%)</label><input id="loss_warning_percent" type="number" min="0" max="100" step="0.1" value="5"></div><div data-types="icmp"><label>Limite de latência média (ms)</label><input id="latency_warning_ms" type="number" min="1" max="10000" value="100"></div>
</div><div class="notice" id="explanation"></div><div id="testResult" class="notice hidden" role="status"></div><p id="formError" role="alert"></p><div class="actions"><button type="button" id="cancel">Cancelar</button><button type="button" id="test">Testar agora</button><button type="submit" class="primary" id="save">Salvar</button></div></form></dialog>
<script>
const $=id=>document.getElementById(id), labels={icmp:'Ping — ICMP',http:'HTTP / HTTPS',tcp:'TCP',dns:'DNS'};let monitors=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opt={}){const r=await fetch('api/'+path,{...opt,headers:{'Content-Type':'application/json'}});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.error||'Falha na operação');return j}
function typeChanged(){const t=$('tipo').value;document.querySelectorAll('[data-types]').forEach(e=>{const show=e.dataset.types.split(' ').includes(t);e.classList.toggle('hidden',!show);e.querySelectorAll('input,select').forEach(x=>x.disabled=!show)});$('destinationLabel').textContent={icmp:'IP de destino (IPv4)',http:'URL completa',tcp:'IP ou hostname',dns:'Servidor DNS (IP ou hostname)'}[t];$('instance').placeholder={icmp:'172.16.27.51',http:'https://exemplo.com.br/status',tcp:'servidor.exemplo.com.br',dns:'1.1.1.1'}[t];$('destinationHint').textContent=t==='http'?'Use http:// ou https://. O certificado HTTPS é validado.':'';$('timeoutLabel').textContent=t==='icmp'?'Timeout por pacote (segundos)':'Timeout da verificação (segundos)';$('explanation').textContent={icmp:'Múltiplos pacotes medem perda e latência. O Blackbox mantém uma checagem rápida de disponibilidade independente. Todos os links têm a mesma importância.',http:'Verifica o código de resposta. GET e HEAD disponíveis; cabeçalhos personalizados, autenticação e validação do corpo ainda não estão disponíveis.',tcp:'Verifica se o destino aceita uma conexão na porta informada. Não valida o protocolo de aplicação.',dns:'Consulta o registro no servidor escolhido. Sucesso exige resposta DNS sem erro e pelo menos uma resposta. Não compara um valor de registro esperado.'}[t];$('dns_name').required=t==='dns'}
async function load(){try{monitors=await api('monitors');$('message').textContent='';render()}catch(e){$('message').textContent=e.message}}
function render(){const q=$('search').value.toLowerCase(),list=monitors.filter(x=>JSON.stringify(x).toLowerCase().includes(q));$('summary').textContent=`${monitors.length} verificações · ${monitors.filter(x=>x.enabled!==false).length} ativas`;$('empty').hidden=!!list.length;$('rows').innerHTML=list.map(x=>`<tr><td><strong>${esc(x.name||x.instance)}</strong><br>${esc(labels[x.tipo])}</td><td>${esc(x.Cliente)} / ${esc(x.Unidade)}<br>${esc(x.Provedor)}</td><td>${esc(x.instance)}${x.tipo==='dns'?'<br>'+esc(x.dns_name)+' · '+esc(x.dns_type):''}</td><td>${esc(x.interval_seconds||30)}s</td><td>${x.enabled===false?'Pausado':'Ativo'}</td><td><button data-action="edit" data-id="${esc(x.id)}">Editar</button> <button class="danger" data-action="delete" data-id="${esc(x.id)}">Excluir</button></td></tr>`).join('')}
function openForm(x){$('form').reset();$('id').value=x?.id||'';$('formError').textContent='';$('testResult').classList.add('hidden');$('title').textContent=x?'Editar verificação':'Nova verificação';if(x){['tipo','name','Cliente','Unidade','Provedor','instance','interval_seconds','timeout_seconds','packet_count','packet_interval_seconds','loss_warning_percent','latency_warning_ms','http_method','expected_status','dns_name','dns_type','dns_port','tcp_port'].forEach(k=>{if(x[k]!=null)$(k).value=x[k]});$('enabled').value=String(x.enabled!==false);$('follow_redirects').value=String(x.follow_redirects!==false);if(x.tipo==='tcp')$('instance').value=x.tcp_host||x.instance.replace(/:\d+$/,'').replace(/^\[|\]$/g,'')}typeChanged();$('modal').showModal()}
function payload(){const t=$('tipo').value,x={tipo:t};['name','Cliente','Unidade','Provedor','instance'].forEach(k=>x[k]=$(k).value.trim());['interval_seconds','timeout_seconds'].forEach(k=>x[k]=Number($(k).value));x.enabled=$('enabled').value==='true';if(t==='icmp')['packet_count','packet_interval_seconds','loss_warning_percent','latency_warning_ms'].forEach(k=>x[k]=Number($(k).value));if(t==='tcp'){x.tcp_host=x.instance;x.tcp_port=Number($('tcp_port').value)}if(t==='http'){x.http_method=$('http_method').value;x.expected_status=Number($('expected_status').value);x.follow_redirects=$('follow_redirects').value==='true'}if(t==='dns'){x.dns_name=$('dns_name').value.trim();x.dns_type=$('dns_type').value;x.dns_port=Number($('dns_port').value)}return x}
$('form').onsubmit=async e=>{e.preventDefault();$('save').disabled=true;try{const id=$('id').value;await api(id?'monitors/'+id:'monitors',{method:id?'PUT':'POST',body:JSON.stringify(payload())});$('modal').close();await load()}catch(e){$('formError').textContent=e.message}finally{$('save').disabled=false}};
$('test').onclick=async()=>{if(!$('form').reportValidity())return;$('test').disabled=true;$('testResult').classList.remove('hidden');$('testResult').textContent='Testando…';try{const r=await api('test',{method:'POST',body:JSON.stringify(payload())});$('testResult').textContent=$('tipo').value==='icmp'?`${r.collector_success?(r.success?'Respondeu':'Sem resposta'):'Falha do coletor ICMP'} · ${r.received}/${r.sent} pacotes · perda ${r.loss_percent??'—'}% · latência média ${r.rtt_ms??'—'} ms`:`${r.success?'Sucesso':'Falha'} · ${r.duration_ms} ms${r.http_status_code?' · HTTP '+r.http_status_code:''}${r.dns_rcode!=null?' · DNS rcode '+r.dns_rcode+' · '+r.dns_answers+' respostas':''}${r.error?' · '+r.error:''}`}catch(e){$('testResult').textContent=e.message}finally{$('test').disabled=false}};
$('rows').onclick=async e=>{const b=e.target.closest('button[data-id]');if(!b)return;const x=monitors.find(x=>x.id===b.dataset.id);if(b.dataset.action==='edit')openForm(x);else if(confirm('Excluir esta verificação? O histórico já coletado será preservado até a retenção expirar.')){try{await api('monitors/'+x.id,{method:'DELETE'});await load()}catch(e){$('message').textContent=e.message}}};$('new').onclick=()=>openForm();$('cancel').onclick=()=>$('modal').close();$('tipo').onchange=typeChanged;$('search').oninput=render;$('reload').onclick=load;typeChanged();load();
</script></body></html>
'''


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "DunkerMonitorAdmin/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}")

    def authorized(self) -> bool:
        password = read_password()
        if not password:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            username, supplied = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(username, "admin") and hmac.compare_digest(supplied.encode(), password.encode())

    def require_auth(self) -> bool:
        if self.path == "/healthz" or self.authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Dunker Monitor"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def json_response(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def payload(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 65536:
                raise ValueError("Requisição muito grande")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("Objeto JSON esperado")
            return value
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Dados inválidos") from exc

    def do_GET(self):
        if not self.require_auth():
            return
        if self.path == "/healthz":
            return self.json_response({"status": "ok"})
        if self.path in {"/", "/index.html"}:
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path == "/api/monitors":
            with LOCK:
                return self.json_response([row for row in load_inventory() if row.get("tipo") in SUPPORTED])
        self.json_response({"error": "Não encontrado"}, 404)

    def do_POST(self):
        if not self.require_auth():
            return
        try:
            payload = self.payload()
            if self.path == "/api/test":
                return self.json_response(test_target(payload))
            if self.path == "/api/monitors":
                row = normalize(payload)
                with LOCK:
                    rows = load_inventory()
                    if any(x.get("tipo") == row["tipo"] and x.get("instance") == row["instance"] and x.get("dns_name", "") == row.get("dns_name", "") and x.get("enabled", True) for x in rows):
                        raise ValueError("Já existe um monitor ativo para esse destino e tipo")
                    rows.append(row)
                    persist(rows)
                return self.json_response(row, 201)
            self.json_response({"error": "Não encontrado"}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def do_PUT(self):
        if not self.require_auth():
            return
        match = re.fullmatch(r"/api/monitors/([0-9a-f-]+)", self.path)
        if not match:
            return self.json_response({"error": "Não encontrado"}, 404)
        try:
            with LOCK:
                rows = load_inventory()
                index = next(i for i, row in enumerate(rows) if row.get("id") == match.group(1))
                updated = normalize(self.payload(), rows[index])
                if any(i != index and x.get("tipo") == updated["tipo"] and x.get("instance") == updated["instance"] and x.get("dns_name", "") == updated.get("dns_name", "") and x.get("enabled", True) for i, x in enumerate(rows)):
                    raise ValueError("Já existe um monitor ativo para esse destino e tipo")
                rows[index] = updated
                persist(rows)
            self.json_response(updated)
        except StopIteration:
            self.json_response({"error": "Monitor não encontrado"}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def do_DELETE(self):
        if not self.require_auth():
            return
        match = re.fullmatch(r"/api/monitors/([0-9a-f-]+)", self.path)
        if not match:
            return self.json_response({"error": "Não encontrado"}, 404)
        with LOCK:
            rows = load_inventory()
            filtered = [row for row in rows if row.get("id") != match.group(1)]
            if len(filtered) == len(rows):
                return self.json_response({"error": "Monitor não encontrado"}, 404)
            persist(filtered)
        self.json_response({"deleted": True})


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not INVENTORY.exists() or (not load_inventory() and not (DATA_DIR / ".initialized").exists()):
        seed = Path("/etc/dunker/inventory.json")
        rows = json.loads(seed.read_text(encoding="utf-8")) if seed.exists() else []
        rows = [normalize(dict(r, name=r.get("name", r["instance"]))) if r.get("tipo") in SUPPORTED else r for r in rows]
        persist(rows)
    rows = load_inventory()
    persist([normalize(dict(r, name=r.get("name", r["instance"])), r if r.get("id") else None) if r.get("tipo") in SUPPORTED else r for r in rows])
    (DATA_DIR / ".initialized").touch()
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
