"""Common services (Sheet 05 Operations health check)."""
from __future__ import annotations

from typing import Any

from django.db import connection, DatabaseError
from django.utils import timezone


def get_system_health() -> dict[str, Any]:
    """Return system health status and data freshness timestamp (Sheet 01 Block 07, Sheet 05)."""
    db_ok = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            db_ok = bool(row and row[0] == 1)
    except DatabaseError:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "data_as_of": timezone.now().isoformat(),
    }
