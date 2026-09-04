# FILE: backend/app/queue/rabbitmq.py
"""RabbitMQ queue (QUEUE_PROVIDER=rabbitmq) — spec 6 / production profile.

Uses `pika` if available. The queue is declared durable with a dead-letter
exchange so jobs that repeatedly fail land in the DLQ (spec 6). The public
contract (publish / start_consumer / stop) is identical to LocalQueue, so the
rest of the system is unaware of which queue backs it.

`pika` is an optional dependency; this module imports it lazily so the LOCAL
profile never requires it.
"""
from __future__ import annotations

import json
import threading

from ..config import get_settings
from ..logging_config import get_logger
from .base import JobHandler, QueueProvider

logger = get_logger("reclaimai.queue.rabbitmq")


class RabbitMQQueue(QueueProvider):
    name = "rabbitmq"

    def __init__(self) -> None:
        self._s = get_settings()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._publish_conn = None
        self._publish_ch = None

    # -- lazy pika import + channel setup ---------------------------------- #
    def _connect(self):
        import pika  # optional dependency

        params = pika.URLParameters(self._s.rabbitmq_url)
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        # Main queue with a dead-letter exchange routing to the DLQ.
        ch.exchange_declare(exchange="reclaimai.dlx", exchange_type="direct", durable=True)
        ch.queue_declare(queue=self._s.dlq_name, durable=True)
        ch.queue_bind(queue=self._s.dlq_name, exchange="reclaimai.dlx", routing_key=self._s.dlq_name)
        ch.queue_declare(queue=self._s.queue_name, durable=True, arguments={
            "x-dead-letter-exchange": "reclaimai.dlx",
            "x-dead-letter-routing-key": self._s.dlq_name,
        })
        return conn, ch

    def publish(self, job: dict) -> None:
        import pika

        if self._publish_ch is None:
            self._publish_conn, self._publish_ch = self._connect()
        self._publish_ch.basic_publish(
            exchange="", routing_key=self._s.queue_name,
            body=json.dumps(job).encode(),
            properties=pika.BasicProperties(delivery_mode=2),  # persistent
        )

    def start_consumer(self, handler: JobHandler) -> None:
        def _consume():
            conn, ch = self._connect()
            ch.basic_qos(prefetch_count=8)

            def _on_message(chan, method, _props, body):
                job = json.loads(body)
                try:
                    handler(job)
                    chan.basic_ack(delivery_tag=method.delivery_tag)  # ack after success
                except Exception as exc:  # nack -> dead-letter after redelivery
                    logger.error("job_failed", extra={"ctx_error": str(exc)})
                    chan.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            ch.basic_consume(queue=self._s.queue_name, on_message_callback=_on_message)
            logger.info("rabbitmq_consumer_started")
            while not self._stop.is_set():
                conn.process_data_events(time_limit=1)

        self._thread = threading.Thread(target=_consume, name="reclaimai-rabbit", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
