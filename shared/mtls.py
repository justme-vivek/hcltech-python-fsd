"""Internal HTTPS client settings. Requires service cert, key and trusted CA in Compose."""
import os, ssl, httpx

def get_ssl_context():
    ca = os.getenv("MTLS_CA_FILE")
    cert = os.getenv("MTLS_CERT_FILE")
    key = os.getenv("MTLS_KEY_FILE")
    if ca and cert and key:
        ctx = ssl.create_default_context(cafile=ca)
        ctx.load_cert_chain(cert, key)
        return ctx
    if os.getenv("REQUIRE_MTLS", "false").lower() == "true":
        raise RuntimeError("mTLS required but certificate configuration is missing")
    return None

def client(timeout=3.0):
    ctx = get_ssl_context()
    if ctx:
        return httpx.Client(timeout=timeout, verify=ctx)
    return httpx.Client(timeout=timeout)
