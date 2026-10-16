"""Transactional outbox + publisher confirms + manual ACK + bounded retries."""
import asyncio
import json
import signal
import threading
import time
import uuid
import os
import argparse
from functools import partial
from pathlib import Path

import pika

from resource_scope import SCOPE
from search_sync import config,connection,sync_album
from project_paths import ROOT,RUNTIME
from resource_scope import OWNER

EXCHANGE='aillisten.dev.events'
QUEUE='aillisten.dev.search'
DEAD_EXCHANGE='aillisten.dev.dead'
DEAD_QUEUE='aillisten.dev.search.dead'
KNOWLEDGE_QUEUE='aillisten.dev.knowledge'
stopping=threading.Event()
publisher_ready=False
knowledge_ready=False


def broker():
    cfg=config()
    client=pika.BlockingConnection(pika.ConnectionParameters(host=cfg['host'],virtual_host=SCOPE.rabbit_vhost,
        credentials=pika.PlainCredentials(SCOPE.rabbit_user,cfg['rabbit_password']),heartbeat=60,
        socket_timeout=5,blocked_connection_timeout=10))
    ch=client.channel()
    ch.exchange_declare(exchange=EXCHANGE,exchange_type='direct',durable=True)
    ch.exchange_declare(exchange=DEAD_EXCHANGE,exchange_type='direct',durable=True)
    ch.queue_declare(queue=DEAD_QUEUE,durable=True)
    ch.queue_bind(queue=DEAD_QUEUE,exchange=DEAD_EXCHANGE,routing_key='search.dead')
    ch.queue_declare(queue=QUEUE,durable=True,arguments={'x-dead-letter-exchange':DEAD_EXCHANGE,'x-dead-letter-routing-key':'search.dead'})
    ch.queue_bind(queue=QUEUE,exchange=EXCHANGE,routing_key='search')
    ch.queue_declare(queue='aillisten.dev.knowledge.dead',durable=True)
    ch.queue_bind(queue='aillisten.dev.knowledge.dead',exchange=DEAD_EXCHANGE,routing_key='knowledge.dead')
    ch.queue_declare(queue=KNOWLEDGE_QUEUE,durable=True,arguments={'x-dead-letter-exchange':DEAD_EXCHANGE,'x-dead-letter-routing-key':'knowledge.dead'})
    ch.queue_bind(queue=KNOWLEDGE_QUEUE,exchange=EXCHANGE,routing_key='knowledge')
    ch.confirm_delivery()
    return client,ch


def publish_loop():
    global publisher_ready
    while not stopping.is_set():
        client=None
        try:
            client,ch=broker()
            publisher_ready=True
            while not stopping.is_set():
                with connection(autocommit=False) as db:
                    with db.cursor() as cur:
                        cur.execute("SELECT id,kind FROM search_outbox WHERE status='RUNNING' AND attempts>=3 AND lease_until<UTC_TIMESTAMP(6) LIMIT 10 FOR UPDATE SKIP LOCKED")
                        expired=cur.fetchall()
                        for expired_id,expired_kind in expired:
                            ch.basic_publish(exchange=DEAD_EXCHANGE,routing_key='knowledge.dead' if expired_kind in {'KNOWLEDGE_CHANGED','PERSONAL_CHANGED'} else 'search.dead',body=json.dumps({'id':expired_id}),mandatory=True,
                                properties=pika.BasicProperties(delivery_mode=2,message_id=expired_id,content_type='application/json'))
                            cur.execute("UPDATE search_outbox SET status='DEAD',lease_token=NULL,lease_until=NULL,error_code='LeaseExpired',updated_at=UTC_TIMESTAMP(6) WHERE id=%s",(expired_id,))
                        cur.execute("UPDATE search_outbox SET status='PENDING',next_attempt=UTC_TIMESTAMP(6),lease_token=NULL WHERE status='RUNNING' AND attempts<3 AND lease_until<UTC_TIMESTAMP(6)")
                        cur.execute("UPDATE search_outbox SET status='PENDING' WHERE status='PUBLISHED' AND published_at<DATE_SUB(UTC_TIMESTAMP(6),INTERVAL 5 MINUTE)")
                        cur.execute("SELECT id,kind FROM search_outbox WHERE status='PENDING' AND attempts<3 AND next_attempt<=UTC_TIMESTAMP(6) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED")
                        row=cur.fetchone()
                        if row:
                            identity=row[0]
                            ch.basic_publish(exchange=EXCHANGE,routing_key='knowledge' if row[1] in {'KNOWLEDGE_CHANGED','PERSONAL_CHANGED'} else 'search',body=json.dumps({'id':identity}),mandatory=True,
                                properties=pika.BasicProperties(delivery_mode=2,message_id=identity,content_type='application/json'))
                            cur.execute("UPDATE search_outbox SET status='PUBLISHED',published_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND status='PENDING'",(identity,))
                        db.commit()
                if not row:
                    stopping.wait(1)
        except Exception as exc:
            publisher_ready=False
            print('outbox publisher retry:',type(exc).__name__,flush=True)
            stopping.wait(3)
        finally:
            if client and client.is_open:
                client.close()


def receive(ch,method,properties,body):
    try:
        identity=json.loads(body)['id']
        if not isinstance(identity,str):
            raise ValueError('Invalid task id')
        if str(uuid.UUID(identity))!=identity:
            raise ValueError('Invalid task id')
    except (ValueError,KeyError,TypeError):
        ch.basic_nack(method.delivery_tag,requeue=False)
        return
    lease=str(uuid.uuid4())
    with connection(autocommit=True) as db:
        with db.cursor() as cur:
            cur.execute("UPDATE search_outbox SET status='RUNNING',attempts=attempts+1,lease_token=%s,lease_until=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 120 SECOND),updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND status IN ('PENDING','PUBLISHED') AND attempts<3",(lease,identity))
            if not cur.rowcount:
                ch.basic_ack(method.delivery_tag)
                return
            cur.execute('SELECT kind,aggregate_id,attempts FROM search_outbox WHERE id=%s',(identity,))
            kind,album,attempt=cur.fetchone()
    renewing=threading.Event()
    def renew():
        while not renewing.wait(20):
            try:
                with connection(autocommit=True) as db:
                    with db.cursor() as cur:
                        cur.execute("UPDATE search_outbox SET lease_until=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 120 SECOND) WHERE id=%s AND status='RUNNING' AND lease_token=%s",(identity,lease))
            except Exception:
                print('task lease renewal failed',flush=True)
    renewal=threading.Thread(target=renew,daemon=True);renewal.start()
    try:
        if kind=='KNOWLEDGE_CHANGED':
            from app.listening.ingestion import process_document
            asyncio.run(process_document(album))
        elif kind=='PERSONAL_CHANGED':
            from personal_knowledge.engine import process_item
            asyncio.run(process_item(album))
        elif kind=='ALBUM_CHANGED':
            asyncio.run(sync_album(album))
        else:
            raise ValueError('Unknown outbox event type')
        with connection(autocommit=True) as db:
            with db.cursor() as cur:
                cur.execute("UPDATE search_outbox SET status='COMPLETED',lease_token=NULL,lease_until=NULL,error_code=NULL,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND lease_token=%s",(identity,lease))
                if not cur.rowcount:
                    raise RuntimeError('Outbox lease changed before completion')
        ch.basic_ack(method.delivery_tag)
        print('search projection completed:',identity,flush=True)
    except Exception as exc:
        with connection(autocommit=True) as db:
            with db.cursor() as cur:
                cur.execute("UPDATE search_outbox SET status=%s,lease_token=NULL,lease_until=NULL,error_code=%s,next_attempt=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL %s SECOND),updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND lease_token=%s",
                    ('DEAD' if attempt>=3 else 'PENDING',type(exc).__name__[:100],min(30,3**attempt),identity,lease))
        if attempt>=3:
            ch.basic_nack(method.delivery_tag,requeue=False)
        else:
            ch.basic_ack(method.delivery_tag)
        print('search projection failed:',identity,type(exc).__name__,flush=True)
    finally:
        renewing.set()


def knowledge_loop():
    global knowledge_ready
    while not stopping.is_set():
        client=None
        try:
            client,ch=broker();ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=KNOWLEDGE_QUEUE,on_message_callback=dispatch,auto_ack=False)
            knowledge_ready=True
            while not stopping.is_set():client.process_data_events(time_limit=1)
        except Exception as exc:
            knowledge_ready=False
            print('knowledge consumer reconnect:',type(exc).__name__,flush=True);stopping.wait(3)
        finally:
            if client and client.is_open:client.close()


def dispatch(ch,method,properties,body):
    # Pika's I/O thread keeps polling heartbeats while the bounded-prefetch job runs.
    class Acknowledgements:
        def basic_ack(self,*args,**kwargs):ch.connection.add_callback_threadsafe(partial(ch.basic_ack,*args,**kwargs))
        def basic_nack(self,*args,**kwargs):ch.connection.add_callback_threadsafe(partial(ch.basic_nack,*args,**kwargs))
    threading.Thread(target=receive,args=(Acknowledgements(),method,properties,body),daemon=True,name='aillisten-message').start()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=ROOT)
    args=parser.parse_args()
    if args.project_root.resolve()!=ROOT:
        raise ValueError('Worker project root mismatch')
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    publisher=threading.Thread(target=publish_loop,name='aillisten-outbox',daemon=True)
    publisher.start()
    threading.Thread(target=knowledge_loop,name='aillisten-knowledge',daemon=True).start()
    while not stopping.is_set():
        client=None
        try:
            client,ch=broker()
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=QUEUE,on_message_callback=dispatch,auto_ack=False)
            print('search consumer ready',flush=True)
            while not stopping.is_set():
                client.process_data_events(time_limit=1)
                heartbeat=RUNTIME/'search-worker.json'
                temporary=heartbeat.with_suffix('.tmp')
                temporary.write_text(json.dumps({'owner':OWNER,'pid':os.getpid(),'updated':time.time(),
                    'ready':publisher_ready and knowledge_ready}),encoding='utf-8')
                os.replace(temporary,heartbeat)
        except Exception as exc:
            print('search consumer reconnect:',type(exc).__name__,flush=True)
            stopping.wait(3)
        finally:
            if client and client.is_open:
                client.close()


if __name__=='__main__':
    main()
