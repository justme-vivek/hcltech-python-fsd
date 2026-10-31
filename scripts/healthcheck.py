import os, ssl, urllib.request
port=os.environ["SERVICE_PORT"]
ctx=ssl.create_default_context(cafile=os.getenv("MTLS_CA_FILE","/certs/ca.crt"))
ctx.load_cert_chain(os.getenv("MTLS_CERT_FILE"),os.getenv("MTLS_KEY_FILE"))
with urllib.request.urlopen(f"https://localhost:{port}/health/ready",context=ctx,timeout=3) as response:
    raise SystemExit(0 if response.status==200 else 1)
