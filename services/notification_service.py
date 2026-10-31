from fastapi import FastAPI, Depends, HTTPException
from shared.storage import init_db, connect
from shared.security import current_user
import uuid
app=FastAPI(title="Notification Service",version="1.0.0")
init_db("notification", """CREATE TABLE IF NOT EXISTS notifications(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,event_id TEXT NOT NULL UNIQUE,type TEXT NOT NULL,
 title TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

def _format_notification(row):
    d = dict(row)
    if "created_at" in d and d["created_at"]:
        d["created_at"] = str(d["created_at"])
    return d

@app.get("/health/live")
def live(): return {"status":"alive","service":"notification-service"}
@app.get("/health/ready")
def ready():
    with connect("notification") as db: db.execute("SELECT 1")
    return {"status":"ready"}
@app.get("/api/v1/notifications")
def history(user=Depends(current_user)):
    with connect("notification") as db: rows=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",(user["sub"],)).fetchall()
    return {"items":[_format_notification(r) for r in rows]}

@app.get("/api/v1/notifications/{notification_id}")
def get_notification(notification_id: str, user=Depends(current_user)):
    with connect("notification") as db:
        row = db.execute("SELECT * FROM notifications WHERE id=? AND user_id=?", (notification_id, user["sub"])).fetchone()
    if not row:
        raise HTTPException(404, "Notification not found")
    return _format_notification(row)

@app.post("/internal/events/order-placed",status_code=202)
def consume_event(event:dict):
    data=event["data"]
    with connect("notification") as db:
        db.execute("""INSERT OR IGNORE INTO notifications(id,user_id,event_id,type,title,message)
        VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),data["user_id"],event["event_id"],"order.placed",
        "Order placed",f"Your order {data['order_id']} was placed. Total: INR {data['total']}"))
    return {"accepted":True,"event_id":event["event_id"]}
