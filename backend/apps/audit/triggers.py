"""PostgreSQL append-only audit trigger helper (Sheet 01 Block 09, Sheet 07 N5, SECURITY_NOTES.md)."""
from __future__ import annotations

from django.db import connection


POSTGRES_AUDIT_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'AuditEvent table is append-only; % operation is forbidden (Sheet 07 N5).', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_event_immutable ON audit_auditevent;
CREATE TRIGGER trg_audit_event_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_auditevent
FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_event_mutation();
"""

SQLITE_AUDIT_TRIGGER_SQL = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_event_no_update
    BEFORE UPDATE ON audit_auditevent
    BEGIN
        SELECT RAISE(ABORT, 'AuditEvent table is append-only; UPDATE operation is forbidden (Sheet 07 N5).');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_event_no_delete
    BEFORE DELETE ON audit_auditevent
    BEGIN
        SELECT RAISE(ABORT, 'AuditEvent table is append-only; DELETE operation is forbidden (Sheet 07 N5).');
    END;
    """,
]


def install_append_only_audit_triggers() -> None:
    """Install database-level append-only triggers on audit_auditevent (PostgreSQL & SQLite test fallback)."""
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(POSTGRES_AUDIT_TRIGGER_SQL)
        elif vendor == "sqlite":
            for stmt in SQLITE_AUDIT_TRIGGER_SQL:
                cursor.execute(stmt)
