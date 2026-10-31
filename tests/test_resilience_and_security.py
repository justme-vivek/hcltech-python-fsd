import os, uuid, json, ssl
import pytest
import httpx
import aio_pika
import asyncio
from shared.security import create_token
from shared.amqp import connection_options

GATEWAY_URL = os.getenv("GATEWAY_URL", "https://gateway:443")
CA_CERT = os.getenv("MTLS_CA_FILE", "/certs/ca.crt")
AMQP_URL = os.getenv("AMQP_URL")

def get_gateway_ssl():
    return ssl.create_default_context(cafile=CA_CERT)

@pytest.fixture
def gateway_client():
    with httpx.Client(base_url=GATEWAY_URL, verify=get_gateway_ssl(), timeout=10.0) as client:
        yield client

def test_security_tampered_and_expired_tokens(gateway_client):
    """Verifies that forged, tampered, expired and invalid tokens are rejected with 401."""
    # Check tampered token.
    valid_token = create_token("user-test-1", "customer", 10)
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.badsignature123"
    r1 = gateway_client.get("/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert r1.status_code == 401

    # Check expired token.
    expired_token = create_token("user-test-1", "customer", -5)
    r2 = gateway_client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert r2.status_code == 401

    # Check malformed header.
    r3 = gateway_client.get("/auth/me", headers={"Authorization": valid_token})
    assert r3.status_code == 401

    # Check missing header.
    r4 = gateway_client.get("/auth/me")
    assert r4.status_code == 401

def test_rbac_customer_denied_admin_routes(gateway_client):
    """Verifies RBAC: customer tokens are denied on admin routes (HTTP 403)."""
    customer_token = create_token("customer-user", "customer", 30)
    headers = {"Authorization": f"Bearer {customer_token}"}

    # Check create protection.
    payload = {"sku": f"DENIED-{uuid.uuid4().hex[:6]}", "name": "Illegal", "price": "10.00", "stock_quantity": 5}
    r = gateway_client.post("/products", json=payload, headers=headers)
    assert r.status_code == 403
    assert "Administrator role required" in r.json().get("detail", "")

    # Check update protection.
    r2 = gateway_client.patch("/products/1", json=payload, headers=headers)
    assert r2.status_code == 403

    # Check delete protection.
    r3 = gateway_client.delete("/products/1", headers=headers)
    assert r3.status_code == 403

def test_rabbitmq_dlq_poison_message():
    """Verifies that an unprocessable/poison message is routed to the Dead Letter Queue after retries."""
    if not AMQP_URL:
        pytest.skip("AMQP_URL must be set for RabbitMQ integration tests")

    async def run_dlq_check():
        connection = await aio_pika.connect_robust(AMQP_URL, **connection_options())
        channel = await connection.channel()
        exchange = await channel.declare_exchange("ecommerce.events", aio_pika.ExchangeType.TOPIC, durable=True)
        dlq = await channel.declare_queue("notification.order-placed.dlq", durable=True)
        
        # Reset queue.
        await dlq.purge()

        # Publish invalid event.
        poison_id = str(uuid.uuid4())
        poison_payload = json.dumps({
            "event_id": poison_id,
            "event_type": "order.placed",
            "poison": True
        })
        # Publish with retry limit.
        msg = aio_pika.Message(
            body=poison_payload.encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers={"x-retry-count": 4},
            content_type="application/json"
        )
        # Send event.
        await channel.default_exchange.publish(msg, routing_key="notification.order-placed")
        
        # Wait for dead-lettering.
        received_in_dlq = False
        for _ in range(15):
            await asyncio.sleep(0.5)
            try:
                incoming = await dlq.get(no_ack=False)
                if incoming:
                    body = json.loads(incoming.body)
                    if body.get("event_id") == poison_id:
                        received_in_dlq = True
                        await incoming.ack()
                        break
                    await incoming.ack()
            except Exception:
                pass
        await connection.close()
        assert received_in_dlq, "Poison message was not routed to DLQ"

    asyncio.run(run_dlq_check())

def test_circuit_breaker_cart_fallback():
    """Verifies cart service circuit breaker trips and returns 503 when product service call fails."""
    customer_token = create_token("cb-customer", "customer", 30)
    headers = {"Authorization": f"Bearer {customer_token}"}
    
    # Use an unavailable product.
    with httpx.Client(base_url=GATEWAY_URL, verify=get_gateway_ssl(), timeout=5.0) as client:
        r = client.post("/cart/items", json={"product_id": 999999, "quantity": 1}, headers=headers)
        assert r.status_code == 503
        assert "circuit breaker" in r.json().get("detail", "").lower() or "unavailable" in r.json().get("detail", "").lower()
