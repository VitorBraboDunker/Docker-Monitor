# Agentes

Inicie a stack para gerar sua CA. Depois execute `sudo python3 scripts/gerar-agente.py --tipo windows|linux --cliente CLIENTE --unidade UNIDADE --instance HOST` na pasta principal.

Uma pasta privada será gerada para cada host com configuração, credencial, certificado público e instruções. Os instaladores do Alloy não estão neste pacote; use a versão oficial compatível. A referência da stack é Alloy v1.20.1.

Não envie `ACESSOS-PRIVADOS.txt` ou a CA privada aos hosts. O pacote de agente contém somente a credencial de ingestão e a CA pública necessárias.
