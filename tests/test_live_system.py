import os, time, uuid, json, ssl, threading
from decimal import Decimal
import pytest
import httpx
import redis
from shared.security import create_token

GATEWAY_URL = os.getenv("GATEWAY_URL", "https://gateway:443")
CA_CERT = os.getenv("MTLS_CA_FILE", "/certs/ca.crt")
CERT_FILE = os.getenv("MTLS_CERT_FILE", "/certs/auth.crt")
KEY_FILE = os.getenv("MTLS_KEY_FILE", "/certs/auth.key")
REDIS_URL = os.getenv("REDIS_URL")

def get_gateway_ssl():
    return ssl.create_default_context(cafile=CA_CERT)

def get_client_ssl():
    ctx = ssl.create_default_context(cafile=CA_CERT)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx

@pytest.fixture
def gateway_client():
    with httpx.Client(base_url=GATEWAY_URL, verify=get_gateway_ssl(), timeout=10.0) as client:
        yield client

@pytest.fixture(scope="session")
def admin_token():
    return create_token("admin-test-id", "admin", 60)

def test_gateway_routing_and_tls(gateway_client):
    """Verifies Gateway routes /auth/, /products, /cart, /orders, /notifications over HTTPS."""
    # Verify auth.
    r = gateway_client.get("/auth/me")
    assert r.status_code == 401
    assert "detail" in r.json()

    # Verify products.
    r = gateway_client.get("/products")
    assert r.status_code == 200
    assert "items" in r.json()

    # Verify cart protection.
    r = gateway_client.get("/cart")
    assert r.status_code == 401

    # Verify order protection.
    r = gateway_client.get("/orders")
    assert r.status_code == 401

    # Verify notification protection.
    r = gateway_client.get("/notifications")
    assert r.status_code == 401

def test_mtls_positive_and_negative():
    """Verifies mTLS requirement: accepted with valid cert, rejected without or with untrusted cert."""
    # Verify trusted access.
    with httpx.Client(verify=get_client_ssl(), timeout=5.0) as client:
        r = client.get("https://auth-service:8001/health/ready")
        assert r.status_code == 200
        assert r.json() == {"status": "ready"}

    # Verify untrusted access.
    with pytest.raises(httpx.RequestError) as exc_info:
        with httpx.Client(verify=get_gateway_ssl(), timeout=5.0) as client:
            client.get("https://auth-service:8001/health/ready")
    err = str(exc_info.value).lower()
    assert "eof" in err or "broken pipe" in err or "certificate" in err or "ssl" in err or "handshake" in err or "reset" in err or "disconnected" in err or "response" in err

def test_redis_caching_and_invalidation(gateway_client, admin_token):
    """Verifies Redis caching of product queries and write-invalidation."""
    if not REDIS_URL:
        pytest.skip("REDIS_URL must be set for Redis integration tests")
    r_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    
    # Reset cache state.
    for k in r_client.scan_iter("products:*"):
        r_client.delete(k)

    # Populate cache.
    r1 = gateway_client.get("/products?page=1&size=5")
    assert r1.status_code == 200
    
    keys = list(r_client.scan_iter("products:*"))
    assert len(keys) > 0, "Redis cache should contain cached product keys"

    # Mutate product data.
    sku = f"CACHE-TEST-{uuid.uuid4().hex[:6]}"
    create_payload = {
        "sku": sku,
        "name": "Cache Invalidation Test",
        "description": "Testing Redis Cache Invalidation",
        "price": "49.99",
        "stock_quantity": 10,
        "is_active": True
    }
    r2 = gateway_client.post("/products", json=create_payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert r2.status_code == 201
    
    # Verify invalidation.
    keys_after = list(r_client.scan_iter("products:*"))
    assert len(keys_after) == 0, "Cache should be invalidated after product mutation"

def test_distributed_rate_limiting(gateway_client):
    """Verifies Redis-backed rate limiting returns HTTP 429 and Retry-After header."""
    test_email = f"rl-{uuid.uuid4().hex[:8]}@example.com"
    # Exercise the request limit.
    responses = []
    for _ in range(7):
        res = gateway_client.post("/auth/register", json={"email": test_email, "password": "SamplePassword123!"})
        responses.append(res)
    
    status_codes = [res.status_code for res in responses]
    assert 429 in status_codes, f"Expected 429 Too Many Requests in {status_codes}"
    r_429 = next(res for res in responses if res.status_code == 429)
    assert "Retry-After" in r_429.headers or "retry-after" in r_429.headers

def test_atomic_stock_reservation_and_oversell_prevention(admin_token):
    """Verifies atomic stock reservation, concurrency protection, and rollback."""
    with httpx.Client(verify=get_client_ssl(), timeout=5.0) as client:
        # Create inventory.
        sku = f"STOCK-{uuid.uuid4().hex[:6]}"
        p_res = client.post(
            "https://product-service:8002/api/v1/products",
            json={"sku": sku, "name": "Atomic Stock Test", "price": "100.00", "stock_quantity": 2, "is_active": True},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert p_res.status_code == 201
        pid = p_res.json()["id"]

        # Reserve inventory.
        res1 = client.post(
            "https://product-service:8002/api/v1/products/reserve",
            json={"items": [{"product_id": pid, "quantity": 1}]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res1.status_code == 200
        p_check = client.get(f"https://product-service:8002/api/v1/products/{pid}").json()
        assert p_check["stock_quantity"] == 1

        # Verify insufficient inventory.
        res2 = client.post(
            "https://product-service:8002/api/v1/products/reserve",
            json={"items": [{"product_id": pid, "quantity": 2}]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res2.status_code == 400
        p_check2 = client.get(f"https://product-service:8002/api/v1/products/{pid}").json()
        assert p_check2["stock_quantity"] == 1  # Verify rollback.

        # Release inventory.
        res3 = client.post(
            "https://product-service:8002/api/v1/products/release",
            json={"items": [{"product_id": pid, "quantity": 1}]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res3.status_code == 200
        p_check3 = client.get(f"https://product-service:8002/api/v1/products/{pid}").json()
        assert p_check3["stock_quantity"] == 2

        # Exercise concurrent reservations.
        results = []
        def attempt_reserve():
            try:
                with httpx.Client(verify=get_client_ssl(), timeout=5.0) as c:
                    r = c.post(
                        "https://product-service:8002/api/v1/products/reserve",
                        json={"items": [{"product_id": pid, "quantity": 1}]},
                        headers={"Authorization": f"Bearer {admin_token}"}
                    )
                    results.append(r.status_code)
            except Exception as e:
                results.append(str(e))

        threads = [threading.Thread(target=attempt_reserve) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        success_count = results.count(200)
        failure_count = results.count(400)
        assert success_count == 2, f"Exactly 2 reservations should succeed, got {success_count}. Results: {results}"
        assert failure_count == 8, f"Remaining 8 should fail with 400, got {failure_count}."
        p_final = client.get(f"https://product-service:8002/api/v1/products/{pid}").json()
        assert p_final["stock_quantity"] == 0, f"Remaining stock must be 0, got {p_final['stock_quantity']}"

def test_full_customer_journey_and_notification(gateway_client, admin_token):
    """Verifies complete flow: Register -> Login -> Product -> Cart -> Order -> Outbox -> RabbitMQ -> Notification."""
    email = f"journey-{uuid.uuid4().hex[:6]}@example.com"
    pwd = "CustomerPassword999!"

    # Register customer.
    reg_res = gateway_client.post("/auth/register", json={"email": email, "password": pwd})
    assert reg_res.status_code == 201

    # Authenticate customer.
    login_res = gateway_client.post("/auth/login", json={"email": email, "password": pwd})
    assert login_res.status_code == 200
    cust_token = login_res.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    # Verify identity.
    me_res = gateway_client.get("/auth/me", headers=cust_headers)
    assert me_res.status_code == 200
    cust_id = me_res.json()["user_id"]

    # Create product.
    prod_res = gateway_client.post(
        "/products",
        json={"sku": f"JOURNEY-{uuid.uuid4().hex[:6]}", "name": "Journey Product", "price": "75.50", "stock_quantity": 5, "is_active": True},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert prod_res.status_code == 201
    prod_id = prod_res.json()["id"]

    # Add cart items.
    add_res = gateway_client.post("/cart/items", json={"product_id": prod_id, "quantity": 2}, headers=cust_headers)
    assert add_res.status_code == 201
    cart = add_res.json()
    assert len(cart["items"]) == 1
    assert cart["total"] == "151.00"

    # Create order.
    idempotency_key = str(uuid.uuid4())
    order_res = gateway_client.post(
        "/orders",
        headers={**cust_headers, "Idempotency-Key": idempotency_key}
    )
    assert order_res.status_code == 201
    order = order_res.json()
    assert order["status"] == "PLACED"
    assert order["subtotal"] == "151.00"
    order_id = order["id"]

    # Verify inventory.
    p_after = gateway_client.get(f"/products/{prod_id}").json()
    assert p_after["stock_quantity"] == 3

    # Verify cart state.
    cart_after = gateway_client.get("/cart", headers=cust_headers).json()
    assert len(cart_after["items"]) == 0

    # Verify idempotency.
    dup_res = gateway_client.post(
        "/orders",
        headers={**cust_headers, "Idempotency-Key": idempotency_key}
    )
    assert dup_res.status_code == 200 or dup_res.status_code == 201
    assert dup_res.json()["id"] == order_id
    # Verify no duplicate reservation.
    p_after_dup = gateway_client.get(f"/products/{prod_id}").json()
    assert p_after_dup["stock_quantity"] == 3

    # Verify order query.
    order_fetch = gateway_client.get(f"/orders/{order_id}", headers=cust_headers)
    assert order_fetch.status_code == 200
    assert order_fetch.json()["id"] == order_id
    assert len(order_fetch.json()["items"]) == 1

    # Verify notification pipeline.
    # Wait for notification delivery.
    notif_found = False
    for _ in range(10):
        time.sleep(0.5)
        n_res = gateway_client.get("/notifications", headers=cust_headers)
        if n_res.status_code == 200 and len(n_res.json()["items"]) > 0:
            for item in n_res.json()["items"]:
                if order_id in item.get("message", ""):
                    notif_found = True
                    assert item["type"] == "order.placed"
                    break
            if notif_found:
                break
    assert notif_found, "Notification for order was not stored by consumer via RabbitMQ pipeline"
