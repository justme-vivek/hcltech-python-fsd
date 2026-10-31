import os
import ssl


def connection_options():
    url = os.getenv("AMQP_URL", "")
    if not url.startswith("amqps://"):
        return {}
    context = ssl.create_default_context(cafile=os.environ["AMQP_TLS_CA_FILE"])
    context.load_cert_chain(
        os.environ["AMQP_TLS_CERT_FILE"],
        os.environ["AMQP_TLS_KEY_FILE"],
    )
    return {"ssl": True, "ssl_context": context}
