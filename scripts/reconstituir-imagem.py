#!/usr/bin/env python3
import argparse,hashlib,os
from pathlib import Path
B=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser(description='Reconstitui e verifica as partes da imagem Docker.');p.add_argument('modo',choices=['separado','unico']);a=p.parse_args();count=2 if a.modo=='separado' else 3
output=B.parent/f'dunker-monitor-{a.modo}-linux-amd64.tar.gz'
expected=next(line.split()[0] for line in (B/'docs/SHA256-IMAGENS.txt').read_text().splitlines() if line.endswith(output.name))
if output.exists():
 if hashlib.file_digest(output.open('rb'),'sha256').hexdigest()==expected:print('Imagem já reconstituída e verificada.');raise SystemExit(0)
 p.error('Arquivo existente tem checksum diferente. Renomeie-o antes de tentar novamente: '+str(output))
parts=[B.parent/f'dunker-{a.modo}-{n:02d}.part' for n in range(1,count+1)]
missing=[f.name for f in parts if not f.is_file()]
if missing:p.error('Faltam partes: '+', '.join(missing))
sha=hashlib.sha256();temp=output.with_suffix('.gz.partial')
try:
 with temp.open('wb') as dst:
  for part in parts:
   print('Lendo '+part.name,flush=True)
   with part.open('rb') as src:
    while block:=src.read(2**20):dst.write(block);sha.update(block)
 if sha.hexdigest()!=expected:temp.unlink(missing_ok=True);p.error('Checksum inválido. Baixe novamente as partes da opção escolhida.')
 temp.replace(output);print('Imagem verificada: '+output.name)
except BaseException:
 temp.unlink(missing_ok=True)
 raise
