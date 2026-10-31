
import os, tempfile, time
# Preserve the runtime environment.
_real_jwt_secret = os.environ.get("JWT_SECRET", "")
_real_db_urls = {k: os.environ.pop(k, None) for k in [
    "DATABASE_URL_AUTH","DATABASE_URL_PRODUCT","DATABASE_URL_CART",
    "DATABASE_URL_ORDER","DATABASE_URL_NOTIFICATION","DATABASE_URL"
]}
# Configure isolated test state.
_unit_test_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_DIR"] = _unit_test_tmpdir
os.environ["JWT_SECRET"] = "integration-test-secret"

from fastapi.testclient import TestClient
from services.auth_service import app as auth_app
from services.product_service import app as product_app
from shared.security import create_token as _create_unit_token

def test_auth_register_login_and_me():
    client=TestClient(auth_app)
    email=f"customer-{int(time.time()*1000)}@example.test"
    assert client.post("/api/v1/auth/register",json={"email":email,"password":"long-password-123"}).status_code==201
    token=client.post("/api/v1/auth/login",json={"email":email,"password":"long-password-123"}).json()["access_token"]
    response=client.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+token})
    assert response.status_code==200
    assert response.json()["role"]=="customer"

def test_product_admin_guard_and_crud():
    client=TestClient(product_app)
    customer=_create_unit_token("customer-1","customer")
    payload={"sku":f"SKU-TEST-{int(time.time()*1000)}","name":"Test Product","description":"demo","price":"19.99","stock_quantity":5}
    denied=client.post("/api/v1/products",json=payload,headers={"Authorization":"Bearer "+customer})
    assert denied.status_code==403
    admin=_create_unit_token("admin-1","admin")
    created=client.post("/api/v1/products",json=payload,headers={"Authorization":"Bearer "+admin})
    assert created.status_code==201
    assert created.json()["price"]=="19.99"
    listed=client.get("/api/v1/products")
    assert listed.status_code==200 and listed.json()["total"]>=1

# Restore the runtime environment.
os.environ["JWT_SECRET"] = _real_jwt_secret
for k, v in _real_db_urls.items():
    if v is not None:
        os.environ[k] = v
