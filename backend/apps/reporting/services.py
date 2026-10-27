"""Services for audited CSV export of the 6 statutory reports (PS Section F.3, Sheet 01 Block 07, Sheet 04 J6, Sheet 07 Q2)."""
from __future__ import annotations

import csv
import io
from typing import Any

from apps.access.services import resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.reporting.selectors import generate_statutory_report


def export_statutory_report_csv(
    *,
    actor: Any,
    report_code: str,
    filters: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Render one of the 6 statutory reports as CSV after enforcing actor scope and recording an audit event."""
    scope = resolve_actor_scope(actor)
    report_payload = generate_statutory_report(actor, report_code=report_code, filters=filters)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=report_payload["columns"])
    writer.writeheader()
    for row in report_payload["rows"]:
        writer.writerow({key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value) for key, value in row.items()})

    csv_text = buffer.getvalue()
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="STATUTORY_REPORT_EXPORTED",
        target_type="StatutoryReport",
        target_id=report_code,
        inputs_snapshot={
            "report_code": report_code,
            "filters": filters or {},
            "row_count": len(report_payload["rows"]),
            "data_as_of": report_payload["data_as_of"],
        },
    )
    return csv_text, report_payload
