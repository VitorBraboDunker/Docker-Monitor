import urllib.request,sys
try:
 for port,path in [(3000,'/api/health'),(9090,'/-/ready'),(9093,'/-/ready'),(3100,'/ready'),(9427,'/healthz'),(8080,'/healthz'),(9115,'/metrics'),(9116,'/metrics'),(12345,'/-/ready')]:
  with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=3) as r:
   if r.status!=200:sys.exit(1)
except Exception:sys.exit(1)
