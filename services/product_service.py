import os
from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from decimal import Decimal
from shared.storage import init_db, connect
from shared.security import current_user, require_admin
from shared.rate_limit import check_rate_limit
from shared.cache import get_json, set_json, delete_pattern

app = FastAPI(title="Product Service", version="1.0.0")
init_db("product", """CREATE TABLE IF NOT EXISTS products(
 id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 description TEXT DEFAULT '', price TEXT NOT NULL, stock_quantity INTEGER NOT NULL,
 is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
_cache = {}
class ProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=150)
    description: str = ""
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    stock_quantity: int = Field(ge=0)
    is_active: bool = True

class StockReservationItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)

class StockReservationRequest(BaseModel):
    items: list[StockReservationItem]

def serialize(row):
    d = dict(row)
    d["price"] = str(d["price"])
    d["is_active"] = bool(d["is_active"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = str(d["created_at"])
    return d

@app.get("/health/live")
def live(): return {"status":"alive","service":"product-service"}
@app.get("/health/ready")
def ready():
    with connect("product") as db: db.execute("SELECT 1")
    return {"status":"ready"}

@app.get("/api/v1/products")
def list_products(q: str|None=None, page: int=Query(1,ge=1), size: int=Query(20,ge=1,le=100)):
    check_rate_limit("products-list", 120, 60)
    key=f"{q}:{page}:{size}"
    cached = get_json("products:"+key)
    if cached is not None: return cached
    if not os.getenv("REDIS_URL") and key in _cache: return _cache[key]
    with connect("product") as db:
        sql="SELECT * FROM products WHERE is_active=1"; args=[]
        if q: sql += " AND (name LIKE ? OR sku LIKE ?)"; args += [f"%{q}%",f"%{q}%"]
        total=db.execute("SELECT COUNT(*) AS total FROM products WHERE is_active=1").fetchone()["total"]
        rows=db.execute(sql+" ORDER BY id LIMIT ? OFFSET ?", args+[size,(page-1)*size]).fetchall()
    result={"items":[serialize(r) for r in rows],"page":page,"size":size,"total":total}
    _cache[key]=result
    set_json("products:"+key, result, ttl=45)
    return result

@app.get("/api/v1/products/{product_id}")
def get_product(product_id:int):
    with connect("product") as db: row=db.execute("SELECT * FROM products WHERE id=? AND is_active=1",(product_id,)).fetchone()
    if not row: raise HTTPException(404,"Product not found")
    return serialize(row)

@app.post("/api/v1/products",status_code=201)
def create_product(body:ProductIn,user=Depends(current_user)):
    require_admin(user)
    try:
        with connect("product") as db:
            cur=db.execute("INSERT INTO products(sku,name,description,price,stock_quantity,is_active) VALUES(?,?,?,?,?,?) RETURNING id",
                (body.sku,body.name,body.description,str(body.price),body.stock_quantity,int(body.is_active)))
            pid=cur.fetchone()["id"]
    except Exception: raise HTTPException(409,"SKU already exists")
    _cache.clear()
    delete_pattern("products:*")
    return get_product(pid)

@app.patch("/api/v1/products/{product_id}")
def update_product(product_id:int,body:ProductIn,user=Depends(current_user)):
    require_admin(user)
    with connect("product") as db:
        cur=db.execute("UPDATE products SET sku=?,name=?,description=?,price=?,stock_quantity=?,is_active=? WHERE id=?",
            (body.sku,body.name,body.description,str(body.price),body.stock_quantity,int(body.is_active),product_id))
    if not cur.rowcount: raise HTTPException(404,"Product not found")
    _cache.clear()
    delete_pattern("products:*")
    with connect("product") as db: row=db.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    return serialize(row)

@app.delete("/api/v1/products/{product_id}",status_code=204)
def delete_product(product_id:int,user=Depends(current_user)):
    require_admin(user)
    with connect("product") as db: cur=db.execute("UPDATE products SET is_active=0 WHERE id=?",(product_id,))
    if not cur.rowcount: raise HTTPException(404,"Product not found")
    _cache.clear()
    delete_pattern("products:*")

@app.post("/api/v1/products/reserve", status_code=200)
def reserve_stock(body: StockReservationRequest, user=Depends(current_user)):
    """Atomically reserves stock for the requested items.
    Rolls back atomically if any item has insufficient stock.
    """
    if not body.items:
        raise HTTPException(400, "No items to reserve")
    reserved_items = []
    with connect("product") as db:
        for item in body.items:
            cur = db.execute(
                "UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ? AND is_active = 1 AND stock_quantity >= ?",
                (item.quantity, item.product_id, item.quantity)
            )
            if not cur.rowcount:
                raise HTTPException(400, f"Insufficient stock or inactive product for product_id {item.product_id}")
            row = db.execute(
                "SELECT id, name, price FROM products WHERE id=?",
                (item.product_id,)
            ).fetchone()
            reserved_items.append({
                "product_id": row["id"],
                "name": row["name"],
                "quantity": item.quantity,
                "unit_price": str(row["price"]),
            })
    _cache.clear()
    delete_pattern("products:*")
    return {"status": "reserved", "items": reserved_items}

@app.post("/api/v1/products/release", status_code=200)
def release_stock(body: StockReservationRequest, user=Depends(current_user)):
    """Releases previously reserved stock back to inventory."""
    with connect("product") as db:
        for item in body.items:
            db.execute(
                "UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?",
                (item.quantity, item.product_id)
            )
    _cache.clear()
    delete_pattern("products:*")
    return {"status": "released"}
