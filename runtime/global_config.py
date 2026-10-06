"""Single authoritative credential document, locked across collector processes."""
import contextlib, fcntl, json, os, tempfile
from pathlib import Path
ROOT=Path(os.environ.get('DNK_CONFIG','/etc/dunker'))
FILE=Path(os.environ.get('DNK_CREDENTIALS',str(ROOT/'global/credentials.json')))
DOMAINS=ROOT/'global/domains.json'
@contextlib.contextmanager
def transaction():
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with open(str(FILE)+'.lock','a') as lock:
        os.chmod(str(FILE)+'.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        value=json.loads(FILE.read_text()) if FILE.exists() else {}
        yield value
        fd,temp=tempfile.mkstemp(dir=FILE.parent)
        try:
            with os.fdopen(fd,'w') as out:json.dump(value,out,ensure_ascii=False,indent=2)
            os.chmod(temp,0o600);os.replace(temp,FILE)
        finally:
            if os.path.exists(temp):os.unlink(temp)
def read():
    return json.loads(FILE.read_text()) if FILE.exists() else {}
def get(section,key,default=None):return read().get(section,{}).get(key,default)
def put(section,key,value):
    with transaction() as cfg:cfg.setdefault(section,{})[key]=value
def replace(section,value):
    with transaction() as cfg:cfg[section]=value
