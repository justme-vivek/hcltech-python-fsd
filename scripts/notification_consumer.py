"""RabbitMQ consumer with bounded retry, delayed retry queues and a terminal DLQ."""
import asyncio, json, os, uuid
import aio_pika
from shared.storage import connect, init_db
from shared.amqp import connection_options

NOTIF_SCHEMA = """CREATE TABLE IF NOT EXISTS notifications(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,event_id TEXT NOT NULL UNIQUE,type TEXT NOT NULL,
 title TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""

async def main():
    try:
        init_db("notification", NOTIF_SCHEMA)
    except Exception as e:
        print(f"notification consumer schema init deferred: {e}", flush=True)
    url=os.getenv("AMQP_URL","amqp://app:app-password@rabbitmq:5672/")
    while True:
        try:
            connection=await aio_pika.connect_robust(url, **connection_options())
            channel=await connection.channel()
            await channel.set_qos(prefetch_count=20)
            exchange=await channel.declare_exchange("ecommerce.events",aio_pika.ExchangeType.TOPIC,durable=True)
            retry_exchange=await channel.declare_exchange("ecommerce.retry",aio_pika.ExchangeType.DIRECT,durable=True)
            dlx=await channel.declare_exchange("ecommerce.dlx",aio_pika.ExchangeType.DIRECT,durable=True)
            main_queue=await channel.declare_queue("notification.order-placed",durable=True)
            await main_queue.bind(exchange,routing_key="order.placed")
            retry_queues=[]
            for attempt, delay in ((1,5000),(2,15000),(3,30000)):
                q=await channel.declare_queue(f"notification.retry.{attempt}",durable=True,
                    arguments={"x-message-ttl":delay,"x-dead-letter-exchange":"ecommerce.events",
                               "x-dead-letter-routing-key":"order.placed"})
                await q.bind(retry_exchange,routing_key=f"retry.{attempt}")
                retry_queues.append(q)
            dead=await channel.declare_queue("notification.order-placed.dlq",durable=True)
            await dead.bind(dlx,routing_key="notification.failed")
            async with main_queue.iterator() as messages:
                async for message in messages:
                    try:
                        event=json.loads(message.body)
                        data=event["data"]
                        with connect("notification") as db:
                            db.execute("""INSERT OR IGNORE INTO notifications(id,user_id,event_id,type,title,message)
                                VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),data["user_id"],event["event_id"],
                                "order.placed","Order placed",
                                f"Your order {data['order_id']} was placed. Total: INR {data['total']}"))
                        await message.ack()
                    except Exception as exc:
                        attempt=int((message.headers or {}).get("x-retry-count",0))+1
                        if attempt<=3:
                            retry=aio_pika.Message(body=message.body,delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                headers={"x-retry-count":attempt},content_type="application/json")
                            await retry_exchange.publish(retry,routing_key=f"retry.{attempt}")
                        else:
                            failed=aio_pika.Message(body=message.body,delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                headers={"failure":str(exc)[:200]},content_type="application/json")
                            await dlx.publish(failed,routing_key="notification.failed")
                        await message.ack()
        except Exception as exc:
            print(f"notification consumer reconnecting: {type(exc).__name__}: {exc}",flush=True)
            await asyncio.sleep(3)

if __name__=="__main__": asyncio.run(main())
