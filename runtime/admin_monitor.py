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
import snmp_manager as snmp
import sharepoint_proxy
import grafana_access


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
MONITOR_FIELDS = {'tipo','name','Cliente','Unidade','Provedor','instance','enabled',
    'interval_seconds','timeout_seconds','packet_count','packet_interval_seconds',
    'latency_warning_ms','loss_warning_percent','http_method','expected_status',
    'follow_redirects','tcp_host','tcp_port','dns_name','dns_type','dns_port','id','criticality'}

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


def snmp_rows():
    return [r for r in load_inventory() if r.get('managed_snmp')]


def snmp_auths():
    return snmp.read_json(snmp.PRIVATE / 'credentials.json', {})


def save_devices(rows, auths):
    """Validate exporter first; roll back local files and exporter on write failure."""
    paths=[INVENTORY, DATA_DIR/'snmp.json', snmp.PRIVATE/'credentials.json', snmp.PRIVATE/'snmp-managed.yml']
    previous={p:p.read_bytes() if p.exists() else None for p in paths}
    old_rows=load_inventory();old_auths=snmp_auths()
    snmp.apply(rows,auths)
    try:
        snmp.atomic(snmp.PRIVATE/'credentials.json',auths)
        atomic_json(INVENTORY,rows)
        atomic_json(DATA_DIR/'snmp.json',snmp.targets(rows,snmp.read_json(DATA_DIR/'snmp.json',[])))
    except Exception:
        for p,body in previous.items():
            if body is not None:
                temporary=p.with_suffix(p.suffix+'.rollback');temporary.write_bytes(body)
                os.chmod(temporary,0o600 if p.parent==snmp.PRIVATE else 0o644);os.replace(temporary,p)
            elif p.exists(): p.unlink()
        try: snmp.apply(old_rows,old_auths)
        except ValueError: pass
        raise ValueError('Falha ao gravar a configuração. Confira as permissões dos volumes.') from None


def test_device(payload):
    # The same lock covers temporary auth changes, CRUD and exporter reloads.
    with LOCK:
        rows=load_inventory();auths=snmp_auths()
        current=next((r for r in rows if r.get('managed_snmp') and r['id']==payload.get('id')),None)
        row,auth=snmp.normalize(payload,current,auths.get(current['id']) if current else None)
        trial_rows=[r for r in rows if r.get('id')!=row['id']]+[row]
        trial_auths=dict(auths);trial_auths[row['id']]=auth
        snmp.apply(trial_rows,trial_auths)
        try: result=snmp.discover(row)
        finally:
            snmp.apply(rows,auths)
        return result


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
    if set(payload) - MONITOR_FIELDS:
        raise ValueError('Campo de monitor inválido')
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


PAGE_FILE = Path(os.environ.get("DNK_ADMIN_PAGE", "/etc/dunker/admin/index.html"))



class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "DunkerMonitorAdmin/1.0"

    def end_headers(self):
        for value in getattr(self, 'grafana_session_cookies', []):
            self.send_header('Set-Cookie', value)
        super().end_headers()

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}")

    def require_auth(self) -> bool:
        return grafana_access.authorize(self)

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
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise ValueError('Use application/json')
            origin=self.headers.get('Origin')
            if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
                raise ValueError('Origem não permitida')
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
        legacy = {'/': 'links', '/index.html': 'links', '/sharepoint/': 'sharepoint'}
        if self.path in legacy:
            self.send_response(302)
            self.send_header('Location', '/a/dunker-integracoes-app/' + legacy[self.path])
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self.require_auth():
            return
        if grafana_access.handle(self): return
        if sharepoint_proxy.handle(self): return
        if self.path == "/healthz":
            return self.json_response({"status": "ok"})
        if self.path in {"/", "/index.html"}:
            body = PAGE_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path == "/api/monitors":
            with LOCK:
                return self.json_response([row for row in load_inventory() if row.get("tipo") in SUPPORTED and not row.get("managed_snmp")])
        if self.path == '/api/devices':
            with LOCK:
                auths=snmp_auths()
                return self.json_response([snmp.public(r,auths.get(r['id'])) for r in snmp_rows()])
        self.json_response({"error": "Não encontrado"}, 404)

    def do_POST(self):
        if not self.require_auth():
            return
        if grafana_access.handle(self): return
        if sharepoint_proxy.handle(self): return
        try:
            payload = self.payload()
            if self.path == '/api/devices/test':
                return self.json_response(test_device(payload))
            if self.path == '/api/devices':
                with LOCK:
                    rows=load_inventory();auths=snmp_auths()
                    row,auth=snmp.normalize(payload)
                    if any(r.get('managed_snmp') and r['instance']==row['instance'] for r in rows):
                        raise ValueError('Equipamento já cadastrado; edite o cadastro existente')
                    rows.append(row);auths[row['id']]=auth;save_devices(rows,auths)
                return self.json_response(snmp.public(row,auth),201)
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
        if grafana_access.handle(self): return
        if sharepoint_proxy.handle(self): return
        device=re.fullmatch(r'/api/devices/([0-9a-f-]+)',self.path)
        if device:
            try:
                with LOCK:
                    rows=load_inventory();auths=snmp_auths()
                    index=next(i for i,r in enumerate(rows) if r.get('managed_snmp') and r['id']==device[1])
                    row,auth=snmp.normalize(self.payload(),rows[index],auths.get(device[1]))
                    if any(i!=index and r.get('managed_snmp') and r['instance']==row['instance'] for i,r in enumerate(rows)):
                        raise ValueError('Equipamento já cadastrado')
                    rows[index]=row;auths[row['id']]=auth;save_devices(rows,auths)
                return self.json_response(snmp.public(row,auth))
            except StopIteration: return self.json_response({'error':'Equipamento não encontrado'},404)
            except Exception as exc: return self.json_response({'error':str(exc)},400)
        match = re.fullmatch(r"/api/monitors/([0-9a-f-]+)", self.path)
        if not match:
            return self.json_response({"error": "Não encontrado"}, 404)
        try:
            with LOCK:
                rows = load_inventory()
                index = next(i for i, row in enumerate(rows) if row.get("id") == match.group(1) and row.get("tipo") in SUPPORTED and not row.get("managed_snmp"))
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
        if grafana_access.handle(self): return
        if sharepoint_proxy.handle(self): return
        origin=self.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
            return self.json_response({'error':'Origem não permitida'},403)
        device=re.fullmatch(r'/api/devices/([0-9a-f-]+)',self.path)
        if device:
            try:
                with LOCK:
                    rows=load_inventory();auths=snmp_auths()
                    filtered=[r for r in rows if not (r.get('managed_snmp') and r['id']==device[1])]
                    if len(filtered)==len(rows): return self.json_response({'error':'Equipamento não encontrado'},404)
                    auths.pop(device[1],None);save_devices(filtered,auths)
                return self.json_response({'deleted':True})
            except Exception as exc: return self.json_response({'error':str(exc)},400)
        match = re.fullmatch(r"/api/monitors/([0-9a-f-]+)", self.path)
        if not match:
            return self.json_response({"error": "Não encontrado"}, 404)
        with LOCK:
            rows = load_inventory()
            filtered = [row for row in rows if not (row.get("id") == match.group(1) and row.get("tipo") in SUPPORTED and not row.get("managed_snmp"))]
            if len(filtered) == len(rows):
                return self.json_response({"error": "Monitor não encontrado"}, 404)
            persist(filtered)
        self.json_response({"deleted": True})


def bootstrap_row(row):
    if row.get('tipo') not in SUPPORTED:
        return row
    payload = {k: v for k, v in row.items() if k in MONITOR_FIELDS}
    payload['name'] = row.get('name', row['instance'])
    return normalize(payload, row if row.get('id') else None)


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not INVENTORY.exists() or (not load_inventory() and not (DATA_DIR / ".initialized").exists()):
        seed = Path("/etc/dunker/inventory.json")
        rows = json.loads(seed.read_text(encoding="utf-8")) if seed.exists() else []
        rows = [bootstrap_row(r) for r in rows]
        persist(rows)
    rows = load_inventory()
    persist([bootstrap_row(r) for r in rows])
    (DATA_DIR / ".initialized").touch()
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
