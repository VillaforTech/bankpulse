"""Abrupt-process recovery with real Kafka and SQLite, in disposable test topics.

Executed inside the isolated analytics component container, never the shared stack.
Fault injection lives only here; production Runtime and Store are exercised unchanged.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.admin import KafkaAdminClient, NewTopic

from analytics import runtime
from analytics.domain import iso
from analytics.store import Store

EXIT_FAULT = 73
FAULT_OFFSET = 2


def worker(db, topic, group, mode):
    runtime.TOPIC, runtime.GROUP = topic, group
    store = Store(db, "2026-01-01T00:00:00Z")
    original_ingest = store.ingest

    def ingest(raw, partition, offset, **kwargs):
        if mode == "before_persist" and offset == FAULT_OFFSET:
            os._exit(EXIT_FAULT)
        return original_ingest(raw, partition, offset, **kwargs)

    class Consumer(KafkaConsumer):
        def commit(self, offsets=None):
            hit = any(v.offset == FAULT_OFFSET + 1 for v in offsets.values())
            if hit and mode == "after_persist_before_ack":
                os._exit(EXIT_FAULT)
            result = super().commit(offsets)
            if hit and mode == "after_ack":
                os._exit(EXIT_FAULT)
            return result

    store.ingest = ingest
    runtime.KafkaConsumer = Consumer
    runner = runtime.Runtime(store)
    original_health = runner.set_health

    def health(**values):
        original_health(**values)
        if mode == "recover" and values.get("caught_up"):
            runner.stop.set()

    runner.set_health = health
    runner.consume()
    store.close()


def fixtures(now):
    rows = []

    def add(session, kind, **payload):
        version = 1 + sum(e["aggregateId"] == session for e in rows)
        rows.append(dict(eventId=f"{session}-{version}", eventType=kind,
                         schemaVersion=1, aggregateId=session, aggregateVersion=version,
                         occurredAt=iso(now), payload=dict(sessionId=session, **payload)))

    for session, shares in (("closed", ("60", "40")), ("open", ("60",))):
        add(session, "SplitCreated", createdAt=iso(now), totalAmount="100", currency="USD")
        for index, share in enumerate(shares):
            add(session, "ParticipantAdded", participantId=f"p{index}", memberId=f"m{index}", shareAmount=share)
            add(session, "ParticipantAuthorized", participantId=f"p{index}", paymentReference="demo")
        if session == "closed":
            add(session, "SplitCompleted", closedAt=iso(now))
    return rows


def run():
    broker = os.environ["KAFKA_BOOTSTRAP"]
    admin = KafkaAdminClient(bootstrap_servers=broker)
    results = []
    try:
        for mode in ("before_persist", "after_persist_before_ack", "after_ack"):
            suffix = uuid.uuid4().hex
            topic, group = f"crash-test-{suffix}", f"crash-test-{suffix}"
            admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
            try:
                with tempfile.TemporaryDirectory(prefix="crash-recovery-") as directory:
                    db = str(Path(directory) / "state.sqlite")
                    now = time.time()
                    events = fixtures(now)
                    producer = KafkaProducer(bootstrap_servers=broker, acks="all")
                    observer = KafkaConsumer(bootstrap_servers=broker, group_id=group, enable_auto_commit=False)
                    tp = TopicPartition(topic, 0)
                    try:
                        def send():
                            for item in events:
                                producer.send(topic, key=item["aggregateId"].encode(), value=json.dumps(item).encode()).get(timeout=10)

                        def child(fault):
                            return subprocess.run([sys.executable, __file__, "worker", db, topic, group, fault],
                                                  timeout=40, capture_output=True, text=True)

                        send()
                        failed = child(mode)
                        assert failed.returncode == EXIT_FAULT, (mode, failed.returncode, failed.stderr)
                        persisted = FAULT_OFFSET if mode == "before_persist" else FAULT_OFFSET + 1
                        acknowledged = FAULT_OFFSET + 1 if mode == "after_ack" else FAULT_OFFSET
                        store = Store(db)
                        assert store.checkpoint(0) == persisted
                        assert store.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == persisted
                        store.close()
                        assert observer.committed(tp) == acknowledged

                        for replay in (False, True):
                            if replay:
                                send()
                            recovered = child("recover")
                            assert recovered.returncode == 0, recovered.stderr
                            store = Store(db)
                            snap = store.publish(now + 130, connected=True, caught_up=True, last_poll=now + 130, lag=0)
                            assert snap["valid"], snap
                            assert snap["kpis"]["counts"] == dict(sessions=2, closedWindow=1, validClosedWindow=1, staleOpen=1)
                            assert snap["kpis"]["B-K1"]["value"] == 100
                            assert snap["kpis"]["B-K2"]["value"] == {"USD": "0"}
                            assert snap["kpis"]["B-K3"]["value"] == {"USD": "60"}
                            assert snap["dataRevision"] == len(events)
                            assert snap["diagnostics"]["duplicates"] == (len(events) if replay else 0)
                            assert store.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == len(events)
                            assert store.checkpoint(0) == len(events) * (2 if replay else 1)
                            store.close()
                            assert observer.committed(tp) == len(events) * (2 if replay else 1)
                        results.append(dict(scenario=mode, result="PASS", crashExit=EXIT_FAULT,
                                            durableOffsetAtCrash=persisted, brokerOffsetAtCrash=acknowledged,
                                            uniqueEvents=len(events), replayedEvents=len(events),
                                            finalOffset=2 * len(events), kpis=snap["kpis"]))
                    finally:
                        producer.close()
                        observer.close(autocommit=False)
            finally:
                admin.delete_topics([topic])
    finally:
        admin.close()
    print(json.dumps(dict(scope="real Kafka, abrupt process exit, durable SQLite, restart and replay", checks=results)))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker(*sys.argv[2:])
    else:
        run()
