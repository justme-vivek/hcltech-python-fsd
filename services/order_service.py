from fastapi import FastAPI, Depends, HTTPException, Header
from shared.storage import init_db, connect
from shared.security import current_user
from decimal import Decimal
import uuid, json, os, httpx
from shared.mtls import client as mtls_client
app=FastAPI(title="Order Service",version="1.0.0")
CART_URL=os.getenv("CART_SERVICE_URL","http://127.0.0.1:8003")
PRODUCT_URL=os.getenv("PRODUCT_SERVICE_URL","http://127.0.0.1:8002")
init_db("order", """CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,status TEXT NOT NULL,subtotal TEXT NOT NULL,
 idempotency_key TEXT NOT NULL,event_id TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id,idempotency_key));
 CREATE TABLE IF NOT EXISTS order_items(
 id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL,product_id INTEGER NOT NULL,
 product_name TEXT NOT NULL,unit_price TEXT NOT NULL,quantity INTEGER NOT NULL,line_total TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS outbox_events(
 event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,payload TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 0);""")

@app.get("/health/live")
def live(): return {"status":"alive","service":"order-service"}
@app.get("/health/ready")
def ready():
    with connect("order") as db: db.execute("SELECT 1")
    return {"status":"ready"}

def _format_order(row):
    d = dict(row)
    if "created_at" in d and d["created_at"]:
        d["created_at"] = str(d["created_at"])
    return d

@app.post("/api/v1/orders",status_code=201)
def create_order(user=Depends(current_user), idempotency_key:str=Header(...,alias="Idempotency-Key")):
    with connect("order") as db:
        existing=db.execute("SELECT * FROM orders WHERE user_id=? AND idempotency_key=?",
                             (user["sub"],idempotency_key)).fetchone()
        if existing:
            return _format_order(existing)
    try:
        with mtls_client(timeout=3) as c:
            cart_resp = c.get(CART_URL+"/api/v1/cart",headers={"Authorization":"Bearer "+_token_for_internal(user)})
            cart_resp.raise_for_status()
            cart = cart_resp.json()
    except Exception as exc:
        raise HTTPException(503,f"Cart service unavailable: {exc}")
    if not cart.get("items"):
        raise HTTPException(400,"Cart is empty")

    reserve_payload = {
        "items": [{"product_id": item["product_id"], "quantity": item["quantity"]} for item in cart["items"]]
    }
    # Reserve inventory.
    try:
        with mtls_client(timeout=3) as c:
            res_resp = c.post(
                PRODUCT_URL + "/api/v1/products/reserve",
                json=reserve_payload,
                headers={"Authorization": "Bearer " + _token_for_internal(user)}
            )
            if res_resp.status_code == 400:
                detail = res_resp.json().get("detail", "Insufficient stock")
                raise HTTPException(400, f"Stock reservation failed: {detail}")
            res_resp.raise_for_status()
            reservation = res_resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"Product service unavailable for stock reservation: {exc}")

    reserved_items = reservation.get("items", [])
    if len(reserved_items) != len(cart["items"]):
        try:
            with mtls_client(timeout=3) as c:
                c.post(
                    PRODUCT_URL + "/api/v1/products/release",
                    json=reserve_payload,
                    headers={"Authorization": "Bearer " + _token_for_internal(user)},
                )
        except Exception:
            pass
        raise HTTPException(503, "Product service returned an invalid stock reservation")
    subtotal=Decimal("0.00")
    for item in reserved_items:
        price=Decimal(item["unit_price"])
        subtotal += price * item["quantity"]
    oid,event_id=str(uuid.uuid4()),str(uuid.uuid4())
    payload={"event_id":event_id,"event_type":"order.placed","schema_version":1,
             "producer":"order-service","data":{"order_id":oid,"user_id":user["sub"],
             "total":str(subtotal.quantize(Decimal("0.01"))),"currency":"INR"}}
    try:
        with connect("order") as db:
            db.execute("INSERT INTO orders(id,user_id,status,subtotal,idempotency_key,event_id) VALUES(?,?,?,?,?,?)",
                       (oid,user["sub"],"PLACED",str(subtotal.quantize(Decimal("0.01"))),idempotency_key,event_id))
            for item in reserved_items:
                db.execute("INSERT INTO order_items(order_id,product_id,product_name,unit_price,quantity,line_total) VALUES(?,?,?,?,?,?)",
                     (oid,item["product_id"],item["name"],item["unit_price"],item["quantity"],
                     str((Decimal(item["unit_price"])*item["quantity"]).quantize(Decimal("0.01")))))
            db.execute("INSERT INTO outbox_events(event_id,event_type,payload) VALUES(?,?,?)",
                       (event_id,"order.placed",json.dumps(payload)))
    except Exception:
        with connect("order") as db:
            existing = db.execute(
                "SELECT * FROM orders WHERE user_id=? AND idempotency_key=?",
                (user["sub"], idempotency_key),
            ).fetchone()
        if existing:
            try:
                with mtls_client(timeout=3) as c:
                    c.post(
                        PRODUCT_URL + "/api/v1/products/release",
                        json=reserve_payload,
                        headers={"Authorization": "Bearer " + _token_for_internal(user)},
                    )
            except Exception:
                pass
            return _format_order(existing)
        # Release inventory on failure.
        try:
            with mtls_client(timeout=3) as c:
                c.post(PRODUCT_URL + "/api/v1/products/release", json=reserve_payload, headers={"Authorization": "Bearer " + _token_for_internal(user)})
        except Exception:
            pass
        raise

    # Clear the cart.
    try:
        with mtls_client(timeout=3) as c:
            c.delete(CART_URL + "/api/v1/cart", headers={"Authorization": "Bearer " + _token_for_internal(user)})
    except Exception:
        pass

    return {"id":oid,"user_id":user["sub"],"status":"PLACED","subtotal":str(subtotal.quantize(Decimal("0.01"))),"event_id":event_id}

def _token_for_internal(user):
    from shared.security import create_token
    return create_token(user["sub"],user["role"],2)

@app.get("/api/v1/orders")
def list_orders(user=Depends(current_user)):
    with connect("order") as db:
        rows=db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC",(user["sub"],)).fetchall()
    return {"items":[_format_order(r) for r in rows]}

@app.get("/api/v1/orders/{order_id}")
def get_order(order_id:str,user=Depends(current_user)):
    with connect("order") as db:
        order=db.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(order_id,user["sub"])).fetchone()
        if not order:
            raise HTTPException(404,"Order not found")
        items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    res=_format_order(order)
    res["items"]=[dict(i) for i in items]
    return res
