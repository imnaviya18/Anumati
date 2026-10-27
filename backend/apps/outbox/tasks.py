"""Celery tasks for outbox dispatch, worker execution, and stranded work recovery (Sheet 01 Block 08, Sheet 05, Sheet 06 L4, M1-M5)."""
from __future__ import annotations

from typing import Any

from config.celery import app
from apps.outbox.services import (
    execute_outbox_event,
    publish_outbox_batch,
    recover_stranded_outbox_work,
)


@app.task(name="outbox.dispatch_batch")
def dispatch_outbox_batch_task() -> dict[str, Any]:
    """Periodic task triggered by Celery Beat to claim and publish pending outbox events."""
    return publish_outbox_batch()


@app.task(name="outbox.process_event")
def process_outbox_event_task(event_id: str) -> dict[str, Any]:
    """Worker task that claims an outbox event by ID and executes the bounded attempt."""
    return execute_outbox_event(event_id=event_id)


@app.task(name="outbox.recover_stranded")
def recover_stranded_outbox_task() -> dict[str, Any]:
    """Periodic reconciliation sweep reclaiming expired leases and stranded events (Sheet 06 M5)."""
    return recover_stranded_outbox_work()
