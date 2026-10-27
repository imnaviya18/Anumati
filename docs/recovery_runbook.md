# Operations & Recovery Runbook — ANUMATI v2 (Sheets 05, 06 M1–M6, 07 N5, Q3–Q4)

## 1. Operational Metrics (Sheet 05, Sheet 07 Q4)
The operations boundary tracks:
- `outbox_backlog`: Count of pending uncompleted outbox events.
- `queue_age_seconds`: Age of the oldest pending outbox event.
- `stale_leases`: Count of leased outbox/job rows whose lease expiry has passed.
- `failed_jobs`: Count of permanently failed / retry-exhausted jobs awaiting owner resolution.
- `due_lag_seconds`: Age of the oldest unprocessed due-work deadline record.

## 2. Stranded Work & Broker Loss Recovery (Sheet 06 M5)
- Redis is a transient transport only; PostgreSQL owns durable intent (`outbox` and `deadlines`).
- If Redis or a Celery worker crashes, the outbox reconciliation sweep (`M5`) reclaims expired leases and republishes uncompleted events by stable logical ID.
- If Celery Beat experiences downtime, the catch-up scan (`H1`) selects all overdue unprocessed milestones across missed intervals.

## 3. Backup and Restore Procedures (Sheet 07 N5, Q3)
- **Backup (`make backup` / `scripts/backup.sh`):** Creates a timestamped backup bundle containing a consistent PostgreSQL dump (`pg_dump --format=custom`), private file storage archive (`tar`), and SHA-256 manifest.
- **Restore (`make restore` / `scripts/restore.sh`):** Restores the PostgreSQL database and private file storage objects, then runs `scripts/checks.sh` to reconcile file checksums against database document version records and verify append-only audit integrity.
