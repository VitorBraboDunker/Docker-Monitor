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
    "criticality": "alta",
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


def persist(rows: list[dict]) -> None:
    targets = []
    for row in rows:
        if row.get("tipo") != "icmp" or not row.get("enabled", True):
            continue
        targets.append({
            "targets": [row["instance"]],
            "labels": {
                "Cliente": row["Cliente"],
                "Unidade": row["Unidade"],
                "Provedor": row["Provedor"],
                "monitor_id": row["id"],
                "monitor_name": row["name"],
                "criticidade": row["criticality"],
            },
        })
    atomic_json(INVENTORY, rows)
    atomic_json(ICMP_TARGETS, targets)


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
    row["instance"] = str(ipaddress.IPv4Address(str(row.get("instance", "")).strip()))
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
    row["tipo"] = "icmp"
    if row.get("criticality") not in {"baixa", "media", "alta", "critica"}:
        raise ValueError("Criticidade inválida")
    return row


def test_target(payload: dict) -> dict:
    from ping_exporter import probe
    address = str(ipaddress.IPv4Address(str(payload.get("instance", ""))))
    timeout = bounded_number(payload.get("timeout_seconds", 5), "Timeout", 1, 30)
    count = bounded_number(payload.get("packet_count", 5), "Pacotes", 1, 20, True)
    interval = bounded_number(payload.get("packet_interval_seconds", 1), "Intervalo", 0.1, 10)
    result = probe(address, count, timeout, interval)
    return {"success": result["received"] > 0, "collector_success": bool(result["success"]),
            "duration_ms": round(result["duration"] * 1000, 2), "target": address,
            "received": result["received"], "sent": result["sent"],
            "loss_percent": result["loss"] if result["success"] else None,
            "rtt_ms": round(result["rtt"] * 1000, 2) if result["received"] else None}


PAGE = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dunker Monitor — Cadastro</title>
<style>
:root{--navy:#122952;--ink:#1d1826;--blue:#2d6cdf;--green:#24c875;--red:#ef5350;--amber:#ffb020;--bg:#f4f7fb;--line:#dbe3ef}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#1c2940;font:14px Inter,Segoe UI,Arial,sans-serif}
header{background:linear-gradient(115deg,var(--ink),var(--navy));color:#fff;padding:22px 28px;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:20px;margin:0}header p{opacity:.75;margin:5px 0 0}.wrap{max-width:1240px;margin:24px auto;padding:0 18px}
.toolbar,.card{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 4px 18px #17325a0c}.toolbar{padding:16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
button{border:0;border-radius:9px;padding:10px 14px;font-weight:650;cursor:pointer}.primary{background:var(--blue);color:white}.secondary{background:#eaf0fb;color:var(--navy)}.danger{background:#ffe8e8;color:#a21f1f}
input,select{border:1px solid #cbd6e5;border-radius:8px;padding:10px;width:100%;background:#fff}.search{max-width:360px}.summary{margin-left:auto;color:#52657f}
.card{margin-top:16px;overflow:hidden}table{border-collapse:collapse;width:100%}th,td{padding:13px 14px;border-bottom:1px solid #edf1f6;text-align:left;vertical-align:middle}th{background:#f8fafc;color:#64748b;font-size:12px;text-transform:uppercase}.empty{padding:42px;text-align:center;color:#718096}
.pill{display:inline-block;border-radius:99px;padding:5px 9px;font-size:12px;font-weight:700}.on{background:#dcfce7;color:#176b3a}.off{background:#eef1f5;color:#596579}.critica{background:#fee2e2;color:#991b1b}.alta{background:#fff0db;color:#9a4b00}.media{background:#fff9ce;color:#7b6300}.baixa{background:#e0f2fe;color:#075985}
.actions{display:flex;gap:6px}.actions button{padding:7px 9px}.modal{position:fixed;inset:0;background:#0b1220a8;display:none;align-items:center;justify-content:center;padding:18px}.modal.open{display:flex}.dialog{background:white;width:min(880px,100%);max-height:94vh;overflow:auto;border-radius:16px;padding:22px}.dialog h2{margin-top:0}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.field label{display:block;font-weight:650;margin:0 0 6px}.field small{color:#708199}.wide{grid-column:span 3}.form-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}.notice{background:#eaf2ff;border-left:4px solid var(--blue);padding:12px;border-radius:7px;margin:12px 0}.toast{position:fixed;right:20px;bottom:20px;background:#16243a;color:white;padding:13px 16px;border-radius:9px;display:none}.toast.show{display:block}
@media(max-width:800px){.grid{grid-template-columns:1fr}.wide{grid-column:span 1}table,thead,tbody,tr,th,td{display:block}thead{display:none}tr{padding:10px;border-bottom:1px solid var(--line)}td{border:0;padding:5px 12px}.summary{margin-left:0}}
</style></head><body>
<header><div><h1>DUNKER IT · Monitoramento</h1><p>Cadastro visual de links e sondagens ICMP</p></div><div><a href="/" style="color:white">Voltar ao Grafana</a> · <span id="clock"></span></div></header>
<main class="wrap"><div class="toolbar"><input class="search" id="search" placeholder="Pesquisar cliente, unidade, provedor ou IP"><button class="primary" onclick="openForm()">+ Novo monitor</button><button class="secondary" onclick="load()">Atualizar</button><span class="summary" id="summary"></span></div>
<section class="card"><table><thead><tr><th>Monitor</th><th>Cliente / unidade</th><th>Destino</th><th>Coleta</th><th>Estado</th><th>Ações</th></tr></thead><tbody id="rows"></tbody></table><div class="empty" id="empty">Nenhum monitor cadastrado.</div></section></main>
<div class="modal" id="modal"><form class="dialog" id="form"><h2 id="formTitle">Novo monitor de link</h2><div class="notice">O teste multipacote calcula perda e latência média. O Blackbox continuará fazendo a verificação rápida de disponibilidade.</div><input type="hidden" id="id"><div class="grid">
<div class="field wide"><label>Nome do monitor</label><input id="name" required placeholder="Ex.: Onkos SP — Claro"></div>
<div class="field"><label>Cliente</label><input id="Cliente" required></div><div class="field"><label>Unidade</label><input id="Unidade" required placeholder="Ex.: SP"></div><div class="field"><label>Provedor</label><input id="Provedor" required></div>
<div class="field"><label>IP de destino (rede local ou público)</label><input id="instance" required placeholder="Ex.: 186.0.0.1"></div><div class="field"><label>Criticidade</label><select id="criticality"><option value="baixa">Baixa</option><option value="media">Média</option><option value="alta" selected>Alta</option><option value="critica">Crítica</option></select></div><div class="field"><label>Estado</label><select id="enabled"><option value="true">Ativo</option><option value="false">Pausado</option></select></div>
<div class="field"><label>Executar a cada (segundos)</label><input id="interval_seconds" type="number" min="10" max="3600" value="30"><small>Mínimo: 10 segundos</small></div><div class="field"><label>Timeout por pacote (segundos)</label><input id="timeout_seconds" type="number" min="1" max="30" step="0.5" value="5"></div><div class="field"><label>Quantidade de pacotes</label><input id="packet_count" type="number" min="1" max="20" value="5"></div>
<div class="field"><label>Intervalo entre pacotes (segundos)</label><input id="packet_interval_seconds" type="number" min="0.1" max="10" step="0.1" value="1"></div><div class="field"><label>Atenção: latência acima de (ms)</label><input id="latency_warning_ms" type="number" min="1" value="100"></div><div class="field"><label>Atenção: perda acima de (%)</label><input id="loss_warning_percent" type="number" min="0" max="100" step="0.1" value="5"></div>
</div><div id="testResult"></div><div class="form-actions"><button type="button" class="secondary" onclick="closeForm()">Cancelar</button><button type="button" class="secondary" onclick="testNow()">Testar agora</button><button class="primary" type="submit">Salvar monitor</button></div></form></div><div class="toast" id="toast"></div>
<script>
let monitors=[];const fields=['name','Cliente','Unidade','Provedor','instance','criticality','interval_seconds','timeout_seconds','packet_count','packet_interval_seconds','latency_warning_ms','loss_warning_percent'];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(t){let e=document.getElementById('toast');e.textContent=t;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),2600)}
async function api(url,opt={}){let r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt});let j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.error||'Falha na operação');return j}
async function load(){monitors=await api('api/monitors');render()}
function render(){let q=document.getElementById('search').value.toLowerCase();let list=monitors.filter(x=>JSON.stringify(x).toLowerCase().includes(q));document.getElementById('summary').textContent=`${monitors.filter(x=>x.enabled).length} ativos · ${monitors.length} cadastrados`;let b=document.getElementById('rows');b.innerHTML=list.map(x=>`<tr><td><strong>${esc(x.name)}</strong><br><span class="pill ${esc(x.criticality)}">${esc(x.criticality)}</span></td><td>${esc(x.Cliente)}<br><small>${esc(x.Unidade)} · ${esc(x.Provedor)}</small></td><td><code>${esc(x.instance)}</code></td><td>${esc(x.packet_count)} pacotes / ${esc(x.interval_seconds)}s<br><small>timeout ${esc(x.timeout_seconds)}s</small></td><td><span class="pill ${x.enabled?'on':'off'}">${x.enabled?'Ativo':'Pausado'}</span></td><td><div class="actions"><button class="secondary" onclick="edit('${x.id}')">Editar</button><button class="danger" onclick="removeMonitor('${x.id}')">Excluir</button></div></td></tr>`).join('');document.getElementById('empty').style.display=list.length?'none':'block'}
function openForm(x){document.getElementById('form').reset();document.getElementById('id').value='';document.getElementById('formTitle').textContent='Novo monitor de link';document.getElementById('testResult').innerHTML='';if(x){document.getElementById('id').value=x.id;fields.forEach(f=>document.getElementById(f).value=x[f]);document.getElementById('enabled').value=String(x.enabled);document.getElementById('formTitle').textContent='Editar monitor'}document.getElementById('modal').classList.add('open')}
function closeForm(){document.getElementById('modal').classList.remove('open')}function edit(id){openForm(monitors.find(x=>x.id===id))}
function payload(){let x={};fields.forEach(f=>x[f]=document.getElementById(f).value);['interval_seconds','timeout_seconds','packet_count','packet_interval_seconds','latency_warning_ms','loss_warning_percent'].forEach(f=>x[f]=Number(x[f]));x.enabled=document.getElementById('enabled').value==='true';return x}
document.getElementById('form').addEventListener('submit',async e=>{e.preventDefault();try{let id=document.getElementById('id').value;await api(id?'api/monitors/'+id:'api/monitors',{method:id?'PUT':'POST',body:JSON.stringify(payload())});closeForm();toast('Monitor salvo');await load()}catch(e){toast(e.message)}});
async function testNow(){let box=document.getElementById('testResult');box.innerHTML='<div class="notice">Testando…</div>';try{let r=await api('api/test',{method:'POST',body:JSON.stringify(payload())});box.innerHTML=`<div class="notice">${r.collector_success?(r.success?'✅ Respondeu':'❌ Sem resposta'):'❌ Falha do coletor: verifique permissão ICMP'} · ${r.received}/${r.sent} pacotes · perda ${r.loss_percent??'—'}% · latência média ${r.rtt_ms??'—'} ms</div>`}catch(e){box.innerHTML=`<div class="notice">❌ ${esc(e.message)}</div>`}}
async function removeMonitor(id){if(!confirm('Excluir este monitor? O histórico já armazenado no Prometheus será preservado até a retenção expirar.'))return;try{await api('api/monitors/'+id,{method:'DELETE'});toast('Monitor excluído');await load()}catch(e){toast(e.message)}}
document.getElementById('search').addEventListener('input',render);document.getElementById('modal').addEventListener('click',e=>{if(e.target.id==='modal')closeForm()});setInterval(()=>document.getElementById('clock').textContent=new Date().toLocaleString('pt-BR'),1000);load().catch(e=>toast(e.message));
</script></body></html>'''


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
                return self.json_response([row for row in load_inventory() if row.get("tipo") == "icmp"])
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
                    if any(x.get("tipo") == "icmp" and x.get("instance") == row["instance"] and x.get("enabled", True) for x in rows):
                        raise ValueError("Já existe um monitor ativo para esse IP")
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
                if any(i != index and x.get("tipo") == "icmp" and x.get("instance") == updated["instance"] and x.get("enabled", True) for i, x in enumerate(rows)):
                    raise ValueError("Já existe um monitor ativo para esse IP")
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
        rows = [normalize(dict(r, name=r.get("name", r["instance"]))) if r.get("tipo") == "icmp" else r for r in rows]
        persist(rows)
    rows = load_inventory()
    if any(r.get("tipo") == "icmp" and not r.get("id") for r in rows):
        persist([normalize(dict(r, name=r.get("name", r["instance"]))) if r.get("tipo") == "icmp" and not r.get("id") else r for r in rows])
    (DATA_DIR / ".initialized").touch()
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
