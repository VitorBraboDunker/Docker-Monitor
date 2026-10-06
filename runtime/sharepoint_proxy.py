"""Authenticated adapter for the existing Dunker administration server."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PRIVATE=Path(os.environ.get('DNK_SP_PRIVATE','/etc/dunker/sharepoint/private'))
UPSTREAM=os.environ.get('DNK_SP_URL','http://sharepoint:9430')


def handle(handler):
    path=urllib.parse.urlsplit(handler.path).path
    assets={'/sharepoint/':('sharepoint.html','text/html; charset=utf-8'),
        '/sharepoint-ui.js':('sharepoint-ui.js','application/javascript; charset=utf-8'),
        '/sharepoint.css':('sharepoint.css','text/css; charset=utf-8')}
    if path in assets and handler.command=='GET':
        name,ctype=assets[path]
        body=(Path(os.environ.get('DNK_ADMIN_PAGE','/etc/dunker/admin/index.html')).parent/name).read_bytes()
        handler.send_response(200);handler.send_header('Content-Type',ctype)
        handler.send_header('Cache-Control','no-store');handler.send_header('Content-Length',str(len(body)))
        handler.end_headers();handler.wfile.write(body);return True
    if not path.startswith('/api/sharepoint/'): return False
    try:
        if handler.command not in ('GET','POST','PUT','DELETE'): raise ValueError()
        origin=handler.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc!=handler.headers.get('Host'):
            handler.json_response({'error':'Origem não permitida'},403);return True
        data=None
        if handler.command in ('POST','PUT'):
            # Reuse the central page's JSON and Origin validation.
            data=json.dumps(handler.payload()).encode()
        token=(PRIVATE/'gateway_token').read_text().strip()
        req=urllib.request.Request(UPSTREAM+'/api/'+path[len('/api/sharepoint/'):],
            data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=handler.command)
        try: response=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as e: response=e
        with response as r:
            body=r.read(25*1024*1024+1)
            if len(body)>25*1024*1024: raise ValueError()
            handler.send_response(r.code);handler.send_header('Content-Type',r.headers.get('Content-Type','application/json'))
            handler.send_header('Cache-Control','no-store');handler.send_header('Content-Length',str(len(body)))
            handler.end_headers();handler.wfile.write(body)
    except Exception:
        handler.json_response({'error':'Não foi possível acessar a integração SharePoint. Confira o serviço sharepoint.'},502)
    return True
