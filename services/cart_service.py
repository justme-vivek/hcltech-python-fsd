from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from shared.storage import init_db, connect
from shared.security import current_user
from shared.resilience import CircuitBreaker
import os, httpx
from shared.mtls import client as mtls_client

app=FastAPI(title="Cart Service",version="1.0.0")
breaker=CircuitBreaker()
PRODUCT_URL=os.getenv("PRODUCT_SERVICE_URL","http://127.0.0.1:8002")
init_db("cart", """CREATE TABLE IF NOT EXISTS cart_items(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,product_id INTEGER NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>0),unit_price TEXT NOT NULL,
 UNIQUE(user_id,product_id))""")
class AddItem(BaseModel):
    product_id:int
    quantity:int=Field(ge=1,le=99)

def product(pid):
    def request():
        with mtls_client(timeout=2) as c:
            r=c.get(f"{PRODUCT_URL}/api/v1/products/{pid}")
            r.raise_for_status(); return r.json()
    try: return breaker.call(request)
    except Exception: raise HTTPException(503,"Product service unavailable (circuit breaker protected)")

@app.get("/health/live")
def live(): return {"status":"alive","service":"cart-service"}
@app.get("/health/ready")
def ready(): return {"status":"ready"}
@app.get("/api/v1/cart")
def get_cart(user=Depends(current_user)):
    with connect("cart") as db: rows=db.execute("SELECT * FROM cart_items WHERE user_id=?",(user["sub"],)).fetchall()
    items=[dict(r) for r in rows]
    total=sum(float(x["unit_price"])*x["quantity"] for x in items)
    return {"items":items,"total":f"{total:.2f}"}

@app.post("/api/v1/cart/items",status_code=201)
def add_item(body:AddItem,user=Depends(current_user)):
    p=product(body.product_id)
    with connect("cart") as db:
        db.execute("""INSERT INTO cart_items(user_id,product_id,quantity,unit_price) VALUES(?,?,?,?)
        ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=cart_items.quantity+excluded.quantity,unit_price=excluded.unit_price""",
        (user["sub"],body.product_id,body.quantity,p["price"]))
    return get_cart(user)

@app.patch("/api/v1/cart/items/{item_id}")
def update_item(item_id:int,body:AddItem,user=Depends(current_user)):
    p=product(body.product_id)
    with connect("cart") as db:
        cur=db.execute("UPDATE cart_items SET quantity=?,unit_price=? WHERE id=? AND user_id=? AND product_id=?",
            (body.quantity,p["price"],item_id,user["sub"],body.product_id))
    if not cur.rowcount: raise HTTPException(404,"Cart item not found")
    return get_cart(user)

@app.delete("/api/v1/cart/items/{item_id}",status_code=204)
def remove_item(item_id:int,user=Depends(current_user)):
    with connect("cart") as db: db.execute("DELETE FROM cart_items WHERE id=? AND user_id=?",(item_id,user["sub"]))
@app.delete("/api/v1/cart",status_code=204)
def clear_cart(user=Depends(current_user)):
    with connect("cart") as db: db.execute("DELETE FROM cart_items WHERE user_id=?",(user["sub"],))
