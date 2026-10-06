"""Same-origin Grafana session authentication and per-integration authorization.

No identity supplied by the browser is trusted. The current organization role is
resolved afresh through Grafana for every request; outage and logout fail closed.
"""
import http.cookies
import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAFANA_URL = os.environ.get('DNK_GRAFANA_URL', 'http://grafana:3000').rstrip('/')
ORG_ID = int(os.environ.get('DNK_GRAFANA_ORG_ID', '1'))
POLICY_FILE = Path(os.environ.get('DNK_ACCESS_FILE', '/etc/dunker/access/private/policy.json'))
LOCK = threading.RLock()
AREAS = ('links', 'snmp', 'sharepoint', 'servidores')
CENTRAL_AREAS = ('links','snmp','sharepoint','servidores','alloy','excluidos','dominios','permissoes')
LEVELS = ('none', 'read', 'edit')
DEFAULT_POLICY = {
    'profiles': {
        'consulta': {'name': 'Consulta', 'permissions': dict.fromkeys(AREAS, 'read')},
        'operador': {'name': 'Operador', 'permissions': dict.fromkeys(AREAS, 'edit')},
        'paineis': {'name': 'Somente dashboards', 'permissions': dict.fromkeys(AREAS, 'none')},
    },
    'role_profiles': {'Viewer': 'consulta', 'Editor': 'operador'},
    'users': {},
}


class AccessError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def grafana_api(path, cookie, updates=None):
    # Paths are code-owned literals. No browser-provided URL or authorization.
    try:
        req = urllib.request.Request(GRAFANA_URL + path, headers={'Cookie': cookie, 'Accept': 'application/json'})
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as response:
            if updates is not None:
                updates.extend(response.headers.get_all('Set-Cookie', []))
            return json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 302):
            raise AccessError('Entre novamente no Grafana.', 401) from None
        raise AccessError('Não foi possível verificar sua sessão no Grafana.', 503) from None
    except (OSError, ValueError):
        raise AccessError('Não foi possível verificar sua sessão no Grafana.', 503) from None


def identity(headers):
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(headers.get('Cookie', ''))
    except http.cookies.CookieError:
        raise AccessError('Entre no Grafana para acessar as configurações.', 401) from None
    name = os.environ.get('DNK_GRAFANA_COOKIE_NAME', 'grafana_session')
    if name not in cookie or not cookie[name].value:
        raise AccessError('Entre no Grafana para acessar as configurações.', 401)
    session = name + '=' + cookie[name].coded_value
    updates = []
    user = grafana_api('/api/user', session, updates)
    for header in updates:
        refreshed = http.cookies.SimpleCookie()
        refreshed.load(header)
        if name in refreshed:
            session = name + '=' + refreshed[name].coded_value
    if not isinstance(user, dict) or int(user.get('id', 0)) <= 0:
        raise AccessError('Sessão inválida.', 401)
    if int(user.get('orgId', 0)) != ORG_ID:
        raise AccessError('Esta central pertence à organização principal do monitoramento.', 403)
    orgs = grafana_api('/api/user/orgs', session, updates)
    org = next((o for o in orgs if int(o.get('orgId', 0)) == ORG_ID), None)
    if not org or org.get('role') not in ('Viewer', 'Editor', 'Admin'):
        raise AccessError('Seu usuário não tem perfil nesta organização.', 403)
    for header in updates:
        refreshed = http.cookies.SimpleCookie()
        refreshed.load(header)
        if name in refreshed:
            session = name + '=' + refreshed[name].coded_value
    return {'id': user['id'], 'login': user.get('login', ''), 'org_id': ORG_ID,
            'role': org['role'], 'cookie': session, '_cookies': updates}


def validate_policy(value):
    if not isinstance(value,dict) or not isinstance(value.get('profiles'),dict):raise ValueError('Política inválida.')
    for profile in value.get('profiles',{}).values():
        if isinstance(profile,dict) and isinstance(profile.get('permissions'),dict):profile['permissions'].setdefault('servidores',profile['permissions'].get('links','none'))
    if not isinstance(value, dict) or set(value) != {'profiles', 'role_profiles', 'users'}:
        raise ValueError('Política inválida.')
    profiles = value['profiles']
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 100:
        raise ValueError('Crie de 1 a 100 perfis.')
    for key, profile in profiles.items():
        if not isinstance(key, str) or not key or len(key) > 80 or not isinstance(profile, dict):
            raise ValueError('Identificador de perfil inválido.')
        if not isinstance(profile.get('name'), str) or not 1 <= len(profile['name'].strip()) <= 120:
            raise ValueError('Informe o nome do perfil.')
        perms = profile.get('permissions')
        if not isinstance(perms, dict) or set(perms) != set(AREAS) or any(v not in LEVELS for v in perms.values()):
            raise ValueError('Selecione sem acesso, consulta ou edição para cada integração.')
    roles = value['role_profiles']
    if not isinstance(roles, dict) or set(roles) != {'Viewer', 'Editor'} or any(v not in profiles for v in roles.values()):
        raise ValueError('Selecione o perfil padrão de Viewer e Editor.')
    users = value['users']
    if not isinstance(users, dict) or len(users) > 10000:
        raise ValueError('Atribuições inválidas.')
    for key, profile in users.items():
        if not isinstance(key, str) or not key.isdigit() or int(key) <= 0 or profile not in profiles:
            raise ValueError('Usuário ou perfil inválido.')
    return value


def load_policy():
    with LOCK:
        try:
            return validate_policy(json.loads(POLICY_FILE.read_text()))
        except FileNotFoundError:
            return json.loads(json.dumps(DEFAULT_POLICY))
        except (ValueError, OSError):
            raise AccessError('Política de permissões inválida. Restaure o arquivo de permissões do backup.', 503) from None


def save_policy(value):
    validate_policy(value)
    with LOCK:
        POLICY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=POLICY_FILE.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, POLICY_FILE)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def permissions(user, policy):
    if user['role'] == 'Admin':
        return {'profile': 'Administrador', 'permissions': dict.fromkeys(AREAS, 'edit'), 'manage_access': True}
    key = policy['users'].get(str(user['id']), policy['role_profiles'][user['role']])
    profile = policy['profiles'][key]
    return {'profile': profile['name'], 'permissions': profile['permissions'], 'manage_access': False}


def classify(path):
    if path in ('/api/alloy','/api/alloy/agents','/api/history/servidores','/api/deleted/servidores') or path.startswith(('/api/alloy/package/','/api/restore/servidores/','/api/servers/servidores/')):return 'servidores'
    if path.startswith('/api/sharepoint/') or path == '/sharepoint/':
        return 'sharepoint'
    if path in ('/api/history/firewalls','/api/deleted/firewalls') or path.startswith('/api/restore/firewalls/'):return 'snmp'
    if path in ('/api/history/links','/api/deleted/links') or path.startswith('/api/restore/links/'):return 'links'
    if path == '/api/devices' or path.startswith('/api/devices/'):
        return 'snmp'
    if path in ('/api/monitors', '/api/test') or path.startswith('/api/monitors/'):
        return 'links'
    return None


def authorize(handler):
    path = urllib.parse.urlsplit(handler.path).path
    if path in ('/healthz','/metrics') and handler.command == 'GET':
        return True
    try:
        # Query-bearing aliases are rejected before the old exact-match router.
        if handler.path != path:
            raise AccessError('Endereço inválido.', 404)
        if handler.command != 'GET':
            origin = urllib.parse.urlsplit(handler.headers.get('Origin', ''))
            if origin.scheme not in ('http', 'https') or origin.netloc != handler.headers.get('Host'):
                raise AccessError('Origem não permitida.', 403)
            if handler.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise AccessError('Origem não permitida.', 403)
        user = identity(handler.headers)
        handler.grafana_session_cookies = user.get('_cookies', [])
        policy = load_policy()
        access = permissions(user, policy)
        handler.grafana_user = user
        handler.grafana_access = access
        if path in ('/central.js','/central.css') and handler.command=='GET':return True
        if path.startswith('/central/') and handler.command=='GET':
            area=path[len('/central/'):]
            if area not in CENTRAL_AREAS:raise AccessError('Não encontrado.',404)
            permitted=access['manage_access'] if area in ('permissoes','dominios') else any(p!='none' for p in access['permissions'].values()) if area=='excluidos' else access['permissions']['servidores' if area=='alloy' else area]!='none'
            if not permitted:raise AccessError('Seu perfil não permite acessar esta integração.',403)
            return True
        if path == '/api/access/me':
            if handler.command != 'GET':
                raise AccessError('Método não permitido.', 405)
            return True
        if path.startswith('/api/access/'):
            if not access['manage_access']:
                raise AccessError('Somente Admin pode gerenciar permissões.', 403)
            return True
        if path=='/api/status' and handler.command=='GET':return True
        if path=='/api/global/status':
            if not access['manage_access']:raise AccessError('Somente Admin pode gerenciar agentes e configurações globais.',403)
            return True
        area = classify(path)
        if area is None:
            raise AccessError('Não encontrado.', 404)
        required = 'read' if handler.command == 'GET' else 'edit'
        if LEVELS.index(access['permissions'][area]) < LEVELS.index(required):
            raise AccessError('Seu perfil não permite esta operação nesta integração.', 403)
        return True
    except AccessError as exc:
        if exc.status==401 and handler.command=='GET' and path in {'/central/'+a for a in CENTRAL_AREAS}:
            handler.send_response(302);handler.send_header('Location','/login?redirectTo='+urllib.parse.quote('/monitoramento'+path,safe=''));handler.send_header('Content-Length','0');handler.send_header('Cache-Control','no-store');handler.end_headers()
        else:handler.json_response({'error': str(exc)}, exc.status)
        return False
    except (TypeError, ValueError, KeyError):
        handler.json_response({'error': 'Não foi possível verificar as permissões.'}, 503)
        return False


def handle(handler):
    path = handler.path
    if not path.startswith('/api/access/'):
        return False
    try:
        if path == '/api/access/me' and handler.command == 'GET':
            user = {k: v for k, v in handler.grafana_user.items() if k not in ('cookie', '_cookies')}
            handler.json_response(dict(user, **handler.grafana_access))
        elif path == '/api/access/policy' and handler.command == 'GET':
            handler.json_response(load_policy())
        elif path == '/api/access/users' and handler.command == 'GET':
            users = grafana_api('/api/org/users', handler.grafana_user['cookie'])
            handler.json_response([{'id': u['userId'], 'login': u.get('login', ''), 'name': u.get('name', ''), 'role': u['role']} for u in users])
        elif path == '/api/access/policy' and handler.command == 'PUT':
            value = handler.payload()
            save_policy(value)
            handler.json_response({'saved': True})
        else:
            handler.json_response({'error': 'Não encontrado.'}, 404)
    except AccessError as exc:
        handler.json_response({'error': str(exc)}, exc.status)
    except ValueError as exc:
        handler.json_response({'error': str(exc)}, 400)
    except OSError:
        handler.json_response({'error': 'Não foi possível salvar as permissões.'}, 503)
    return True
