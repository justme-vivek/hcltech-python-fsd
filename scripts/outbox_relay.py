"""Publishes committed order outbox rows to RabbitMQ; marks published only after broker confirm."""
import asyncio, json, os, time
import aio_pika
from shared.storage import connect, init_db
from shared.amqp import connection_options

ORDER_SCHEMA = """CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,status TEXT NOT NULL,subtotal TEXT NOT NULL,
 idempotency_key TEXT NOT NULL,event_id TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id,idempotency_key));
 CREATE TABLE IF NOT EXISTS order_items(
 id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL,product_id INTEGER NOT NULL,
 product_name TEXT NOT NULL,unit_price TEXT NOT NULL,quantity INTEGER NOT NULL,line_total TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS outbox_events(
 event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,payload TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 0);"""

async def main():
    try:
        init_db("order", ORDER_SCHEMA)
    except Exception as e:
        print(f"outbox relay schema init deferred: {e}", flush=True)
    url=os.getenv("AMQP_URL","amqp://app:app-password@rabbitmq:5672/")
    while True:
        try:
            connection=await aio_pika.connect_robust(url, **connection_options())
            channel=await connection.channel(publisher_confirms=True)
            exchange=await channel.declare_exchange("ecommerce.events",aio_pika.ExchangeType.TOPIC,durable=True)
            while True:
                with connect("order") as db:
                    rows=db.execute("SELECT event_id,event_type,payload FROM outbox_events WHERE published=0 ORDER BY event_id LIMIT 50").fetchall()
                for row in rows:
                    msg=aio_pika.Message(body=row["payload"].encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=row["event_id"],content_type="application/json")
                    await exchange.publish(msg,routing_key=row["event_type"],mandatory=True)
                    with connect("order") as db:
                        db.execute("UPDATE outbox_events SET published=1 WHERE event_id=?",(row["event_id"],))
                await asyncio.sleep(1)
        except Exception as exc:
            print(f"outbox relay reconnecting: {type(exc).__name__}: {exc}",flush=True)
            await asyncio.sleep(3)

if __name__=="__main__": asyncio.run(main())
